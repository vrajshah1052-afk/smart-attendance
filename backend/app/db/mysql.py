"""MySQL access layer (SQLAlchemy Core + PyMySQL, connection pooling).

Transactions are explicit: `with transaction() as conn:` commits on success
and rolls back on any exception, which gives us the "whole class marked
atomically" guarantee for group attendance.
"""
from __future__ import annotations

import logging
import ssl
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Sequence

from sqlalchemy import bindparam, create_engine, event, text
from sqlalchemy.engine import URL, Connection, CursorResult, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.core.utils import normalize_row

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_engine_lock = threading.Lock()

# session variables read by the audit triggers
_RESET_AUDIT_VARS = "SET @app_user_id = NULL, @audit_reason = NULL, @audit_action = NULL"


def _on_checkout(dbapi_conn: Any, _record: Any, _proxy: Any) -> None:
    """Pooled connections are reused: never leak audit context between requests."""
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute(_RESET_AUDIT_VARS)
    finally:
        cursor.close()


def _ssl_context(ca: str) -> ssl.SSLContext:
    """TLS for managed MySQL. With a CA (PEM text or path) the server is verified."""
    if not ca:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    if "-----BEGIN" in ca:
        # env vars often carry the PEM on one line with literal \n
        return ssl.create_default_context(cadata=ca.replace("\\n", "\n"))
    return ssl.create_default_context(cafile=ca)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                s = get_settings()
                url = URL.create(
                    "mysql+pymysql",
                    username=s.mysql_app_user,
                    password=s.mysql_app_password,
                    host=s.mysql_host,
                    port=s.mysql_port,
                    database=s.mysql_database,
                    query={"charset": "utf8mb4"},
                )
                connect_args: dict[str, Any] = {"connect_timeout": 5, "read_timeout": 60, "write_timeout": 60}
                if s.mysql_ssl:
                    connect_args["ssl"] = _ssl_context(s.mysql_ssl_ca)
                if s.mysql_time_zone:  # NOW() in triggers/procedures must be college time
                    connect_args["init_command"] = f"SET time_zone = '{s.mysql_time_zone}'"
                engine = create_engine(
                    url,
                    pool_size=s.mysql_pool_size,
                    max_overflow=s.mysql_pool_size,
                    pool_pre_ping=True,
                    pool_recycle=1800,
                    pool_timeout=10,
                    connect_args=connect_args,
                )
                event.listen(engine, "checkout", _on_checkout)
                _engine = engine
    return _engine


def dispose_engine() -> None:
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
            _engine = None


@contextmanager
def transaction() -> Iterator[Connection]:
    """BEGIN ... COMMIT / ROLLBACK."""
    with get_engine().begin() as conn:
        yield conn


@contextmanager
def read_conn() -> Iterator[Connection]:
    """Connection for read-only work (rolled back on close)."""
    with get_engine().connect() as conn:
        yield conn


def _prepare(sql: str, params: dict[str, Any] | None) -> tuple[Any, dict[str, Any]]:
    params = dict(params or {})
    stmt = text(sql)
    expanding = [k for k, v in params.items() if isinstance(v, (list, tuple, set, frozenset))]
    if expanding:
        for key in expanding:
            params[key] = list(params[key])
        stmt = stmt.bindparams(*[bindparam(k, expanding=True) for k in expanding])
    return stmt, params


def execute(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> CursorResult:
    stmt, bound = _prepare(sql, params)
    return conn.execute(stmt, bound)


def fetch_all(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [normalize_row(dict(r._mapping)) for r in execute(conn, sql, params)]


def fetch_one(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    row = execute(conn, sql, params).first()
    return normalize_row(dict(row._mapping)) if row is not None else None


def fetch_scalar(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> Any:
    return execute(conn, sql, params).scalar()


def call_procedure(conn: Connection, name: str, args: Sequence[Any], out_count: int = 0) -> list[Any]:
    """CALL a stored procedure; OUT parameters are read back via session variables."""
    placeholders = [f":p{i}" for i in range(len(args))]
    outs = [f"@_{name}_o{i}" for i in range(out_count)]
    conn.execute(text(f"CALL {name}({', '.join(placeholders + outs)})"),
                 {f"p{i}": v for i, v in enumerate(args)})
    if not out_count:
        return []
    row = conn.execute(text("SELECT " + ", ".join(outs))).one()
    return list(row)


def call_procedure_resultsets(name: str, args: Iterable[Any]) -> list[list[dict[str, Any]]]:
    """CALL a procedure that returns several result sets (raw DB-API cursor)."""
    raw = get_engine().raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.callproc(name, list(args))
            result_sets: list[list[dict[str, Any]]] = []
            while True:
                if cursor.description:
                    cols = [d[0] for d in cursor.description]
                    result_sets.append([normalize_row(dict(zip(cols, r))) for r in cursor.fetchall()])
                if not cursor.nextset():
                    break
            return result_sets
        finally:
            cursor.close()
            raw.rollback()
    finally:
        raw.close()


@contextmanager
def audit_context(conn: Connection, user_id: int | None, reason: str | None = None,
                  action: str | None = None) -> Iterator[None]:
    """Expose who/why to the audit triggers through session variables."""
    conn.execute(text("SET @app_user_id = :u, @audit_reason = :r, @audit_action = :a"),
                 {"u": user_id, "r": reason, "a": action})
    try:
        yield
    finally:
        try:
            conn.execute(text(_RESET_AUDIT_VARS))
        except SQLAlchemyError:  # connection already broken: nothing to reset
            pass


def ping() -> bool:
    try:
        with read_conn() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


def wait_for_mysql(retries: int, delay: float = 2.0) -> bool:
    for attempt in range(1, retries + 1):
        if ping():
            logger.info("MySQL reachable (attempt %d)", attempt)
            return True
        logger.warning("MySQL not reachable yet (attempt %d/%d)", attempt, retries)
        time.sleep(delay)
    return False
