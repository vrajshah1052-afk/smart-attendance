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
from app.db.mysql import execute, transaction, wait_for_mysql
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


def run_startup() -> dict[str, bool]:
    s = get_settings()
    status = {"mysql": False, "mongo": False}
    if wait_for_mysql(retries=s.mysql_connect_retries):
        status["mysql"] = True
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
