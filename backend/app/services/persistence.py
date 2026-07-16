"""Persistence layer for inference + emission records.

Writes every analyze run's inference trace, activity trace, and totals to a
database (PostgreSQL in prod via DATABASE_URL, SQLite in local dev) and falls
back to the existing CSV seed files when no DB is reachable — so the backend
always boots and never loses data to a missing connection.

Schema follows docs/Inference_Engine.md: masters CSV stay the single source of
truth; this table holds runtime inference only (separation is a core principle).
"""
from __future__ import annotations

import csv
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.config import CALCULATION_DATA_ROOT

try:
    from sqlalchemy import Column, Float, String, Text, create_engine
    from sqlalchemy.orm import DeclarativeBase, Session

    _SQLALCHEMY_AVAILABLE = True
except ImportError:  # pragma: no cover - degrade gracefully
    _SQLALCHEMY_AVAILABLE = False


def _database_url() -> str:
    """DATABASE_URL may be a bare postgresql:// URL; SQLAlchemy wants the +psycopg dialect."""
    url = os.getenv("DATABASE_URL", "sqlite:///" + str(_default_sqlite_path()))
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _default_sqlite_path() -> Path:
    CALCULATION_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    return CALCULATION_DATA_ROOT / "lca_intelligence.db"


if _SQLALCHEMY_AVAILABLE:

    class _Base(DeclarativeBase):
        pass

    class InferenceRecord(_Base):
        __tablename__ = "inference_records"
        inference_id = Column(String, primary_key=True, nullable=False)
        run_id = Column(String, index=True, nullable=False)
        inference_type = Column(String, index=True)
        input_data = Column(Text)
        output_data = Column(Text)
        agent = Column(String)
        confidence_score = Column(Float)
        confidence_label = Column(String)
        timestamp = Column(String, index=True)
        version = Column(String)
        source = Column(Text)
        approval_status = Column(String)
        evidence_json = Column(Text)

    class CarbonCalculation(_Base):
        __tablename__ = "carbon_calculations"
        run_id = Column(String, primary_key=True, nullable=False)
        product_name = Column(String)
        template_id = Column(String, index=True)
        route_id = Column(String, index=True)
        energy_kwh = Column(Float)
        water_l = Column(Float)
        carbon_kgco2e = Column(Float)
        breakdown_json = Column(Text)
        activity_count = Column(Float)
        created_at = Column(String)


def _new_run_id() -> str:
    return datetime.now(UTC).strftime("RUN-%Y%m%dT%H%M%S")


class PersistenceLayer:
    """DB-first persistence with CSV fallback. Thread-safe startup, lazy connect."""

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()
        self._ready = False

    def _ensure_ready(self) -> bool:
        if not _SQLALCHEMY_AVAILABLE:
            return False
        if self._ready:
            return True
        with self._lock:
            if self._ready:
                return True
            try:
                self._engine = create_engine(_database_url(), future=True)
                _Base.metadata.create_all(self._engine)
                self._ready = True
                return True
            except Exception:
                self._engine = None
                self._ready = False
                return False

    def store_run(
        self,
        *,
        product_name: str,
        template_id: str,
        route_id: str,
        totals: dict,
        inference_records: list[dict],
        activity_trace: list[dict],
    ) -> dict:
        run_id = _new_run_id()
        if self._ensure_ready():
            self._store_sql(run_id, product_name, template_id, route_id, totals, inference_records, activity_trace)
            storage = "database"
        else:
            self._store_csv(run_id, product_name, template_id, route_id, totals, inference_records, activity_trace)
            storage = "csv_fallback"
        return {
            "run_id": run_id,
            "storage": storage,
            "inference_records_stored": len(inference_records),
            "activity_records_stored": len(activity_trace),
            "database_url": _database_url(),
        }

    def _store_sql(self, run_id, product_name, template_id, route_id, totals, inference_records, activity_trace):
        with Session(self._engine) as session:
            for record in inference_records:
                conf = record.get("confidence", {}) if isinstance(record.get("confidence"), dict) else {}
                session.add(
                    InferenceRecord(
                        inference_id=f"{run_id}-{record.get('inference_id', '')}",
                        run_id=run_id,
                        inference_type=record.get("inference_type", ""),
                        input_data=record.get("input_data", ""),
                        output_data=record.get("output_data", ""),
                        agent=record.get("agent", ""),
                        confidence_score=float(conf.get("score", 0.0)) if conf else 0.0,
                        confidence_label=conf.get("label", "") if conf else "",
                        timestamp=record.get("timestamp", ""),
                        version=record.get("version", ""),
                        source=record.get("source", ""),
                        approval_status=record.get("approval_status", ""),
                        evidence_json=json.dumps(record.get("evidence", [])),
                    )
                )
            session.add(
                CarbonCalculation(
                    run_id=run_id,
                    product_name=product_name,
                    template_id=template_id,
                    route_id=route_id,
                    energy_kwh=float(totals.get("energy_kwh", 0.0)),
                    water_l=float(totals.get("water_l", 0.0)),
                    carbon_kgco2e=float(totals.get("carbon_kgco2e", 0.0)),
                    breakdown_json=json.dumps(
                        {
                            "transport": totals.get("transport_carbon_kgco2e", 0.0),
                            "chemical": totals.get("chemical_carbon_kgco2e", 0.0),
                        }
                    ),
                    activity_count=float(len(activity_trace)),
                    created_at=datetime.now(UTC).isoformat(),
                )
            )
            session.commit()

    def _store_csv(self, run_id, product_name, template_id, route_id, totals, inference_records, activity_trace):
        _write_csv_rows(
            CALCULATION_DATA_ROOT / "inference_runs.csv",
            ["run_id", "product_name", "template_id", "route_id", "energy_kwh", "water_l", "carbon_kgco2e", "created_at"],
            [
                {
                    "run_id": run_id,
                    "product_name": product_name,
                    "template_id": template_id,
                    "route_id": route_id,
                    "energy_kwh": totals.get("energy_kwh", 0.0),
                    "water_l": totals.get("water_l", 0.0),
                    "carbon_kgco2e": totals.get("carbon_kgco2e", 0.0),
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ],
        )
        _write_csv_rows(
            CALCULATION_DATA_ROOT / "inference_records_runtime.csv",
            ["run_id", "inference_type", "agent", "output_data", "confidence_label", "source"],
            [
                {
                    "run_id": run_id,
                    "inference_type": record.get("inference_type", ""),
                    "agent": record.get("agent", ""),
                    "output_data": record.get("output_data", "")[:500],
                    "confidence_label": (record.get("confidence", {}) or {}).get("label", ""),
                    "source": record.get("source", ""),
                }
                for record in inference_records
            ],
        )

    def list_recent_runs(self, limit: int = 50) -> list[dict]:
        if not self._ensure_ready():
            return self._read_csv_runs()
        with Session(self._engine) as session:
            rows = (
                session.query(CarbonCalculation)
                .order_by(CarbonCalculation.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "run_id": row.run_id,
                    "product_name": row.product_name,
                    "template_id": row.template_id,
                    "route_id": row.route_id,
                    "energy_kwh": row.energy_kwh,
                    "water_l": row.water_l,
                    "carbon_kgco2e": row.carbon_kgco2e,
                    "created_at": row.created_at,
                    "storage": "database",
                }
                for row in rows
            ]

    def _read_csv_runs(self) -> list[dict]:
        path = CALCULATION_DATA_ROOT / "inference_runs.csv"
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row["storage"] = "csv_fallback"
        return rows


def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


persistence = PersistenceLayer()
