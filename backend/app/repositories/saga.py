"""MySQL: durable saga log (each write is its own short transaction)."""
from __future__ import annotations

import json
from typing import Any

from app.db.mysql import execute, fetch_all, transaction


class MySQLSagaRecorder:
    """Persists saga state so compensation can resume after a crash."""

    def start(self, saga_id: str, saga_type: str, subject: str, steps: list[str], created_by: int | None) -> None:
        payload = json.dumps([{"name": s, "status": "PENDING"} for s in steps])
        with transaction() as conn:
            execute(conn, """INSERT INTO saga_log (saga_id, saga_type, subject, status, steps, created_by)
                             VALUES (:id, :t, :s, 'STARTED', :steps, :by)""",
                    {"id": saga_id, "t": saga_type, "s": subject, "steps": payload, "by": created_by})

    def step(self, saga_id: str, step: str, status: str) -> None:
        with transaction() as conn:
            row = conn.exec_driver_sql("SELECT steps FROM saga_log WHERE saga_id = %s FOR UPDATE",
                                       (saga_id,)).first()
            if row is None:
                return
            steps = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            for item in steps:
                if item["name"] == step:
                    item["status"] = status
            execute(conn, "UPDATE saga_log SET steps = :steps WHERE saga_id = :id",
                    {"steps": json.dumps(steps), "id": saga_id})

    def status(self, saga_id: str, status: str, error: str | None = None) -> None:
        with transaction() as conn:
            execute(conn, """UPDATE saga_log SET status = :st, error_message = COALESCE(:err, error_message)
                             WHERE saga_id = :id""", {"st": status, "err": error, "id": saga_id})


def list_sagas(limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    with transaction() as conn:
        rows = fetch_all(conn, f"""SELECT * FROM saga_log {'WHERE status = :st' if status else ''}
                                   ORDER BY created_at DESC LIMIT :limit""", {"st": status, "limit": limit})
    for row in rows:
        if isinstance(row.get("steps"), str):
            row["steps"] = json.loads(row["steps"])
    return rows


def stale_sagas(older_than_minutes: int = 5) -> list[dict[str, Any]]:
    with transaction() as conn:
        rows = fetch_all(conn, """SELECT * FROM saga_log WHERE status IN ('STARTED', 'COMPENSATING')
                                  AND updated_at < NOW(3) - INTERVAL :m MINUTE""", {"m": older_than_minutes})
    for row in rows:
        if isinstance(row.get("steps"), str):
            row["steps"] = json.loads(row["steps"])
    return rows
