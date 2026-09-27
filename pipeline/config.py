"""Configuration and project paths."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Paths:
    root: Path = ROOT

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def raw_trips(self) -> Path:
        return self.raw / "trips"

    @property
    def raw_reference(self) -> Path:
        return self.raw / "reference"

    @property
    def raw_api(self) -> Path:
        return self.raw / "api"

    @property
    def manifest(self) -> Path:
        return self.raw / "manifest.json"

    @property
    def warehouse(self) -> Path:
        return self.root / "warehouse" / "tlc.duckdb"

    @property
    def seeds(self) -> Path:
        return self.root / "seeds"

    @property
    def output(self) -> Path:
        return self.root / "output"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    def ensure(self) -> None:
        for p in (self.raw_trips, self.raw_reference, self.raw_api, self.warehouse.parent,
                  self.output, self.logs, self.docs):
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class Config:
    raw: dict
    paths: Paths = field(default_factory=Paths)

    @classmethod
    def load(cls, path: Path | None = None, root: Path | None = None) -> "Config":
        path = path or ROOT / "config" / "pipeline.toml"
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        return cls(raw=raw, paths=Paths(root or ROOT))

    @property
    def run(self) -> dict:
        return self.raw["run"]

    @property
    def sources(self) -> dict:
        return self.raw["sources"]

    @property
    def validation(self) -> dict:
        return self.raw["validation"]

    @property
    def gates(self) -> dict:
        return self.raw["gates"]

    @property
    def metrics(self) -> dict:
        return self.raw["metrics"]
