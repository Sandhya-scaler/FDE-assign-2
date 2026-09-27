"""Pipeline entry point.

    python -m pipeline run [--months 2024-01 2025-01] [--force-download] [--offline]
    python -m pipeline profile [--months ...]
    python -m pipeline status

Stages per month: ingest -> load -> validate -> gates -> model -> metrics -> reconcile.
Each month is processed independently: a failure in one month is logged, rolled back and
reported, and the other months continue. Exit code is non-zero unless every month published.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager

from . import gates, ingest, load, metrics, model, report, validate
from .config import Config
from .db import connect, finish_run, log_stage, now, start_run
from .profile import profile

log = logging.getLogger("pipeline")


def setup_logging(cfg: Config, run_id: str) -> None:
    cfg.paths.ensure()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(cfg.paths.logs / f"run_{run_id}.log")):
        h.setFormatter(fmt)
        root.addHandler(h)


@contextmanager
def run_lock(cfg: Config):
    """Prevent two runs writing the warehouse at once."""
    lock = cfg.paths.warehouse.with_suffix(".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"Another run holds {lock}. If no run is active, delete the lock file.")
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


class Stage:
    """Times a stage and writes one row to pipeline_stage_log whatever the outcome."""

    def __init__(self, con, run_id, month, name):
        self.con, self.run_id, self.month, self.name = con, run_id, month, name
        self.rows, self.status, self.message = None, "ok", ""

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.status, self.message = "failed", f"{exc_type.__name__}: {exc}"
        log_stage(self.con, self.run_id, self.month, self.name, self.status, self.rows,
                  round(time.perf_counter() - self.t0, 2), self.message)
        return False


def process_month(con, cfg: Config, run_id: str, month: str, args) -> str:
    """Returns month status: published | blocked | source_unavailable | failed."""
    try:
        with Stage(con, run_id, month, "ingest") as st:
            if args.offline:
                st.status, st.message = "skipped", "offline: using preserved raw file"
            else:
                info = ingest.fetch_trip_month(cfg, month, force=args.force_download)
                st.rows, st.message = info["parquet_rows"], info["action"]
        with Stage(con, run_id, month, "load") as st:
            st.rows = load.load_trip_month(con, cfg, month)
        with Stage(con, run_id, month, "validate") as st:
            res = validate.validate_month(con, cfg, month)
            st.rows, st.message = res["valid"], f"valid_rate={res['valid_rate']:.4f}"
        with Stage(con, run_id, month, "gates") as st:
            publishable = gates.run_blocking_gates(con, cfg, month)
            if not publishable:
                st.status, st.message = "blocked", "a fail-severity gate failed; metrics will not be published"
        with Stage(con, run_id, month, "model") as st:
            st.rows = model.build_month(con, cfg, month)
        with Stage(con, run_id, month, "metrics") as st:
            st.rows = len(metrics.compute_month(con, cfg, month, run_id, publishable))
        with Stage(con, run_id, month, "reconcile"):
            gates.run_reconciliation_gates(con, cfg, month)
        return "published" if publishable else "blocked"
    except ingest.SourceUnavailable as e:
        log.error("%s: source not available (%s) - skipping month", month, e)
        return "source_unavailable"
    except Exception:
        log.exception("%s: failed - changes for this month rolled back; other months continue", month)
        return "failed"


def cmd_run(cfg: Config, args) -> int:
    run_id = now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    setup_logging(cfg, run_id)
    months = args.months or cfg.run["months"]
    with run_lock(cfg):
        con = connect(cfg)
        start_run(con, run_id, months, vars(args))
        log.info("run %s started for months %s", run_id, months)
        try:
            with Stage(con, run_id, None, "reference"):
                if not args.offline:
                    ingest.fetch_zone_lookup(cfg, force=args.force_download)
                    ingest.fetch_reference_apis(cfg)
                load.load_reference(con, cfg)
                model.build_dimensions(con, cfg)
        except Exception:
            log.exception("reference data failed - cannot validate any month")
            finish_run(con, run_id, "failed")
            return 2

        status = {m: process_month(con, cfg, run_id, m, args) for m in months}
        with Stage(con, run_id, None, "report"):
            report.export_csvs(con, cfg)
            report.write_evidence_report(con, cfg, run_id, status)

        overall = "success" if all(s == "published" for s in status.values()) else \
            "partial" if any(s == "published" for s in status.values()) else "failed"
        finish_run(con, run_id, overall)
        for m, s in status.items():
            log.info("  %s: %s", m, s)
        log.info("run %s finished: %s", run_id, overall)
        con.close()
    return 0 if overall == "success" else 1


def cmd_status(cfg: Config) -> int:
    con = connect(cfg)
    print("Recent runs:")
    for r in con.execute("select run_id, started_at, finished_at, status, months from pipeline_runs "
                         "order by started_at desc limit 5").fetchall():
        print("  ", *r)
    print("\nLatest metrics status per month:")
    for r in con.execute("select source_month, any_value(status), max(run_id) from metrics_monthly "
                         "group by 1 order by 1").fetchall():
        print("  ", *r)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ingest -> validate -> model -> metrics for the given months")
    r.add_argument("--months", nargs="+", help="YYYY-MM months (default: config/pipeline.toml)")
    r.add_argument("--force-download", action="store_true", help="re-download even if raw copy is verified")
    r.add_argument("--offline", action="store_true", help="use preserved raw files only, no network")
    pr = sub.add_parser("profile", help="profile preserved raw files -> docs/profiling_report.md")
    pr.add_argument("--months", nargs="+")
    sub.add_parser("status", help="show recent runs and published months")
    args = p.parse_args(argv)
    cfg = Config.load()
    if args.cmd == "run":
        return cmd_run(cfg, args)
    if args.cmd == "profile":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        profile(cfg, args.months or cfg.run["months"])
        return 0
    return cmd_status(cfg)


if __name__ == "__main__":
    sys.exit(main())
