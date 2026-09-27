"""DuckDB connection and run-log tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb

from .config import Config

RUN_LOG_DDL = """
create table if not exists pipeline_runs (
    run_id varchar primary key,
    started_at timestamp,
    finished_at timestamp,
    status varchar,            -- running | success | partial | failed
    months varchar,
    args varchar
);
create table if not exists pipeline_stage_log (
    run_id varchar,
    source_month varchar,
    stage varchar,             -- ingest | load | validate | model | metrics | gates
    status varchar,            -- ok | warn | failed | skipped | blocked
    rows bigint,
    seconds double,
    message varchar,
    logged_at timestamp
);
"""


def connect(cfg: Config) -> duckdb.DuckDBPyConnection:
    cfg.paths.ensure()
    con = duckdb.connect(str(cfg.paths.warehouse))
    con.execute(RUN_LOG_DDL)
    return con


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def log_stage(con, run_id: str, month: str | None, stage: str, status: str,
              rows: int | None = None, seconds: float | None = None, message: str = "") -> None:
    con.execute(
        "insert into pipeline_stage_log values (?, ?, ?, ?, ?, ?, ?, ?)",
        [run_id, month, stage, status, rows, seconds, message, now()],
    )


def start_run(con, run_id: str, months: list[str], args: dict) -> None:
    con.execute(
        "insert into pipeline_runs values (?, ?, null, 'running', ?, ?)",
        [run_id, now(), ",".join(months), json.dumps(args, default=str)],
    )


def finish_run(con, run_id: str, status: str) -> None:
    con.execute(
        "update pipeline_runs set finished_at = ?, status = ? where run_id = ?",
        [now(), status, run_id],
    )
