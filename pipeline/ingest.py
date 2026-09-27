"""Stage 1 - Retrieval.

Two retrieval modes feed the pipeline:
  * Files over HTTPS: monthly trip Parquet files + the zone lookup CSV (TLC CloudFront).
  * REST API (Socrata/SODA JSON): Taxi Zones and TLC Industry Indicators (NYC Open Data).
The warehouse then reads everything back with SQL (DuckDB), which is the third mode.

Raw inputs are preserved exactly as received (never edited), and every file is
recorded in data/raw/manifest.json with its source, size, checksum and the
evidence used to decide that the retrieval is complete.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb

from .config import Config
from .db import now

log = logging.getLogger("pipeline.ingest")

USER_AGENT = "fde-tlc-pipeline/1.0"

REQUIRED_TRIP_COLUMNS = {
    "vendorid", "tpep_pickup_datetime", "tpep_dropoff_datetime", "passenger_count",
    "trip_distance", "ratecodeid", "store_and_fwd_flag", "pulocationid", "dolocationid",
    "payment_type", "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
    "improvement_surcharge", "total_amount", "congestion_surcharge", "airport_fee",
}
OPTIONAL_TRIP_COLUMNS = {"cbd_congestion_fee"}  # introduced Jan 2025


class SourceUnavailable(Exception):
    """The source has not published this object (e.g. month not released yet)."""


class RetrievalIncomplete(Exception):
    """Retrieved data failed a completeness check."""


# --------------------------------------------------------------------------- HTTP

def _request(url: str, method: str = "GET", timeout: int = 120):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def _with_retries(fn, what: str, retries: int):
    """Retry transient failures with exponential backoff; surface 403/404 immediately."""
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                # CloudFront answers 403 for objects that do not exist yet.
                raise SourceUnavailable(f"{what}: HTTP {e.code}") from e
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, RetrievalIncomplete) as e:
            err = e
        if attempt == retries:
            raise err
        wait = 2 ** attempt
        log.warning("%s failed (attempt %d/%d): %s - retrying in %ss", what, attempt, retries, err, wait)
        time.sleep(wait)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, timeout: int) -> dict:
    """Stream to a .part file, verify byte count against Content-Length, then atomically rename."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _request(url, timeout=timeout) as resp:
        expected = int(resp.headers.get("Content-Length") or -1)
        etag = (resp.headers.get("ETag") or "").strip('"')
        last_modified = resp.headers.get("Last-Modified")
        got = 0
        with open(tmp, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
    if expected >= 0 and got != expected:
        tmp.unlink(missing_ok=True)
        raise RetrievalIncomplete(f"{url}: received {got} bytes, expected {expected}")
    os.replace(tmp, dest)
    return {"bytes": got, "expected_bytes": expected, "etag": etag, "last_modified": last_modified}


# ----------------------------------------------------------------------- manifest

def load_manifest(cfg: Config) -> dict:
    if cfg.paths.manifest.exists():
        return json.loads(cfg.paths.manifest.read_text())
    return {"files": {}, "latest": {}}


def save_manifest(cfg: Config, manifest: dict) -> None:
    tmp = cfg.paths.manifest.with_suffix(".json.part")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    os.replace(tmp, cfg.paths.manifest)


def _rel(cfg: Config, p: Path) -> str:
    return str(p.relative_to(cfg.paths.root))


# ----------------------------------------------------------------- trip files

def parquet_row_count(path: Path) -> int:
    """Row count declared in the Parquet footer - the producer's own statement of completeness."""
    return duckdb.sql(f"select num_rows from parquet_file_metadata('{path}') limit 1").fetchone()[0]


def parquet_columns(path: Path) -> set[str]:
    rows = duckdb.sql(f"describe select * from read_parquet('{path}')").fetchall()
    return {r[0].lower() for r in rows}


def check_trip_schema(path: Path) -> list[str]:
    """Fail on missing required columns; return any unexpected new columns (schema drift)."""
    cols = parquet_columns(path)
    missing = REQUIRED_TRIP_COLUMNS - cols
    if missing:
        raise RetrievalIncomplete(f"{path.name}: missing required columns {sorted(missing)}")
    return sorted(cols - REQUIRED_TRIP_COLUMNS - OPTIONAL_TRIP_COLUMNS)


def fetch_trip_month(cfg: Config, month: str, force: bool = False) -> dict:
    """Retrieve one month of yellow trips. Skips the download if the local copy is verified unchanged."""
    url = cfg.sources["trip_url_template"].format(month=month)
    dest = cfg.paths.raw_trips / f"yellow_tripdata_{month}.parquet"
    key = _rel(cfg, dest)
    manifest = load_manifest(cfg)
    prev = manifest["files"].get(key)
    timeout, retries = cfg.sources["http_timeout_s"], cfg.sources["http_retries"]

    def head():
        with _request(url, "HEAD", timeout) as r:
            return int(r.headers.get("Content-Length") or -1), (r.headers.get("ETag") or "").strip('"')

    remote_size, remote_etag = _with_retries(head, f"HEAD {url}", retries)

    if (not force and prev and dest.exists() and prev.get("etag") == remote_etag
            and prev.get("bytes") == remote_size and sha256(dest) == prev.get("sha256")):
        log.info("%s: raw file unchanged at source and checksum verified - reusing", month)
        return {**prev, "action": "cached"}

    if prev and prev.get("etag") and prev.get("etag") != remote_etag:
        log.warning("%s: source file changed since last retrieval (etag %s -> %s); re-downloading",
                    month, prev.get("etag"), remote_etag)

    log.info("%s: downloading %s (%.1f MB)", month, url, remote_size / 1e6)
    meta = _with_retries(lambda: _download(url, dest, timeout), f"GET {url}", retries)
    new_cols = check_trip_schema(dest)
    if new_cols:
        log.warning("%s: schema drift - new columns not used by pipeline: %s", month, new_cols)
    entry = {
        "kind": "trip_parquet",
        "source_month": month,
        "source_url": url,
        "retrieved_at": now().isoformat(timespec="seconds"),
        **meta,
        "sha256": sha256(dest),
        "parquet_rows": parquet_row_count(dest),
        "unexpected_columns": new_cols,
        "completeness": "bytes == Content-Length; parquet footer readable; required columns present",
    }
    manifest["files"][key] = entry
    save_manifest(cfg, manifest)
    return {**entry, "action": "downloaded"}


def fetch_zone_lookup(cfg: Config, force: bool = False) -> dict:
    url = cfg.sources["zone_lookup_url"]
    dest = cfg.paths.raw_reference / "taxi_zone_lookup.csv"
    key = _rel(cfg, dest)
    manifest = load_manifest(cfg)
    prev = manifest["files"].get(key)
    if not force and prev and dest.exists() and sha256(dest) == prev["sha256"]:
        return {**prev, "action": "cached"}
    meta = _with_retries(lambda: _download(url, dest, cfg.sources["http_timeout_s"]),
                         f"GET {url}", cfg.sources["http_retries"])
    rows = duckdb.sql(f"select count(*) from read_csv('{dest}')").fetchone()[0]
    entry = {"kind": "reference_csv", "source_url": url, "retrieved_at": now().isoformat(timespec="seconds"),
             **meta, "sha256": sha256(dest), "rows": rows,
             "completeness": "bytes == Content-Length; row count recorded; IDs checked against API in model stage"}
    manifest["files"][key] = entry
    save_manifest(cfg, manifest)
    return {**entry, "action": "downloaded"}


# ------------------------------------------------------------------------- APIs

def _soda_get(cfg: Config, dataset: str, params: dict) -> list[dict]:
    url = f"{cfg.sources['socrata_base']}/{dataset}.json?{urllib.parse.urlencode(params)}"

    def go():
        with _request(url, timeout=cfg.sources["http_timeout_s"]) as r:
            return json.loads(r.read())

    return _with_retries(go, f"GET {url}", cfg.sources["http_retries"])


def fetch_soda_dataset(cfg: Config, name: str, dataset: str, select: str | None = None,
                       where: str | None = None) -> dict:
    """Page through a Socrata dataset and prove completeness by comparing with the server-side count(*)."""
    base: dict = {}
    if where:
        base["$where"] = where
    expected = int(_soda_get(cfg, dataset, {**base, "$select": "count(*) as n"})[0]["n"])

    page, rows, offset = cfg.sources["api_page_size"], [], 0
    while True:
        params = {**base, "$limit": page, "$offset": offset, "$order": ":id"}
        if select:
            params["$select"] = select
        batch = _soda_get(cfg, dataset, params)
        rows.extend(batch)
        log.info("API %s: fetched %d rows (offset %d)", dataset, len(batch), offset)
        if len(batch) < page:
            break
        offset += page

    if len(rows) != expected:
        raise RetrievalIncomplete(f"API {dataset}: got {len(rows)} rows, server count(*) = {expected}")

    stamp = now().strftime("%Y%m%d")
    dest = cfg.paths.raw_api / f"{name}_{stamp}.json"
    payload = {"dataset": dataset, "where": where, "select": select,
               "retrieved_at": now().isoformat(timespec="seconds"), "rows": rows}
    tmp = dest.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, indent=1))
    os.replace(tmp, dest)

    manifest = load_manifest(cfg)
    key = _rel(cfg, dest)
    manifest["files"][key] = {
        "kind": "api_snapshot", "dataset": dataset,
        "source_url": f"{cfg.sources['socrata_base']}/{dataset}.json",
        "where": where, "retrieved_at": payload["retrieved_at"],
        "rows": len(rows), "expected_rows": expected, "sha256": sha256(dest),
        "completeness": "paged row count == server-side count(*)",
    }
    manifest["latest"][name] = key
    save_manifest(cfg, manifest)
    return manifest["files"][key]


def fetch_reference_apis(cfg: Config) -> dict:
    zones = fetch_soda_dataset(cfg, "taxi_zones", cfg.sources["zones_dataset"],
                               select="locationid,borough,zone,shape_area")
    ind = fetch_soda_dataset(cfg, "industry_indicators", cfg.sources["industry_indicators_dataset"],
                             where="license_class='Yellow'")
    return {"taxi_zones": zones, "industry_indicators": ind}


def latest_api_snapshot(cfg: Config, name: str) -> Path:
    key = load_manifest(cfg)["latest"].get(name)
    if not key:
        raise SourceUnavailable(f"No API snapshot for {name}; run without --offline first")
    return cfg.paths.root / key
