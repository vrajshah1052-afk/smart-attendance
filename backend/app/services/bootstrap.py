"""Start-up tasks: wait for databases, schema, first admin, demo accounts."""
from __future__ import annotations

import logging
import secrets

from pymongo.errors import PyMongoError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.core.security import hash_password
from app.db.mongo import get_db, wait_for_mongo
from app.db.mongo_schema import ensure_mongo_schema
from app.db.mysql import execute, fetch_one, transaction, wait_for_mysql
from app.repositories import users as users_repo

logger = logging.getLogger(__name__)


def ensure_accounts() -> None:
    s = get_settings()
    with transaction() as conn:
        if not users_repo.admin_exists(conn, s.admin_email.lower()):
            password = s.admin_password or secrets.token_urlsafe(12)
            users_repo.create_user(conn, username=s.admin_email.lower(), password_hash=hash_password(password),
                                   role="ADMIN", must_change=not s.admin_password)
            if s.admin_password:
                logger.info("Created admin account %s", s.admin_email)
            else:
                logger.warning("Created admin %s with generated password: %s (change it!)", s.admin_email, password)
        if s.demo_user_password:
            activated = users_repo.activate_seeded_accounts(conn, hash_password(s.demo_user_password))
            if activated:
                logger.info("Activated %d seeded demo accounts with DEMO_USER_PASSWORD", activated)
        # keep the DB-side shortage threshold (used by views) in sync with the config
        execute(conn, "UPDATE app_meta SET meta_value = :v WHERE meta_key = 'shortage_threshold'",
                {"v": f"{s.shortage_threshold:g}"})


MIGRATION_002 = """
    ALTER TABLE students
      MODIFY COLUMN face_status
      ENUM('PENDING','PENDING_APPROVAL','ENROLLED','REENROLL_REQUIRED') NOT NULL DEFAULT 'PENDING'"""


def ensure_schema_patches() -> None:
    """Apply db/mysql/migrations idempotently so an existing database keeps working.

    A database created before self sign-up existed has no PENDING_APPROVAL value in
    students.face_status. This runs in its own transaction and swallows its own errors:
    the application MySQL user often has no ALTER grant, and that must not stop the
    rest of the start-up (or roll back the account bootstrap).
    """
    try:
        with transaction() as conn:
            column = fetch_one(conn, """
                SELECT COLUMN_TYPE AS t FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students'
                   AND COLUMN_NAME = 'face_status'""")
            if not column or "PENDING_APPROVAL" in str(column["t"]):
                return
            execute(conn, MIGRATION_002)
        logger.info("students.face_status now accepts PENDING_APPROVAL (migration 002)")
    except SQLAlchemyError as exc:
        logger.error("Could not apply migration 002 (%s). Self sign-ups will fail until a privileged "
                     "user runs db/mysql/migrations/002_signup_approval.sql", exc.__class__.__name__)
        logger.debug("migration 002 error: %s", exc)


def run_startup() -> dict[str, bool]:
    s = get_settings()
    status = {"mysql": False, "mongo": False}
    if wait_for_mysql(retries=s.mysql_connect_retries):
        status["mysql"] = True
        ensure_schema_patches()
        try:
            ensure_accounts()
        except SQLAlchemyError as exc:
            logger.error("Account bootstrap failed: %s", exc)
    else:
        logger.error("MySQL unreachable - starting in degraded mode (endpoints will return 503)")
    if wait_for_mongo(retries=max(5, s.mysql_connect_retries // 2)):
        status["mongo"] = True
        try:
            ensure_mongo_schema(get_db(), s)
        except PyMongoError as exc:
            logger.error("Mongo schema bootstrap failed: %s", exc)
    else:
        logger.error("MongoDB unreachable - logs/embeddings unavailable until it recovers")
    return status
