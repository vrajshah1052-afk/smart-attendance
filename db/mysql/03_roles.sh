#!/bin/bash
# =====================================================================
#  Least-privilege roles & users (GRANT-based security).
#  Runs once on first MySQL container init (after 01_schema / 02_seed).
#  Passwords come from environment variables -> nothing hard-coded.
#
#  role_app_rw        : what the FastAPI backend needs (CRUD + EXECUTE),
#                       audit_log is READ-ONLY (append happens in triggers)
#  role_reporting_ro  : BI / report users - SELECT on views only
#  role_dba           : full control of the schema
#  Also creates attendance_test (same schema, no seed) for pytest.
# =====================================================================

MYSQL_CMD=(mysql -uroot "-p${MYSQL_ROOT_PASSWORD}")
INIT_DIR="$(dirname "${BASH_SOURCE[0]:-$0}")"

echo "[03_roles] creating pytest database attendance_test"
sed -e 's/attendance_db/attendance_test/g' "${INIT_DIR}/01_schema.sql" | "${MYSQL_CMD[@]}"

echo "[03_roles] creating roles and users"
"${MYSQL_CMD[@]}" <<EOSQL
CREATE ROLE IF NOT EXISTS 'role_app_rw', 'role_reporting_ro', 'role_dba';

-- ---------------- application role ----------------
GRANT SELECT, INSERT, UPDATE, DELETE ON attendance_db.students          TO 'role_app_rw';
GRANT SELECT, INSERT, UPDATE, DELETE ON attendance_db.teachers          TO 'role_app_rw';
GRANT SELECT, INSERT, UPDATE, DELETE ON attendance_db.users             TO 'role_app_rw';
GRANT SELECT, INSERT, UPDATE, DELETE ON attendance_db.courses           TO 'role_app_rw';
GRANT SELECT, INSERT, UPDATE, DELETE ON attendance_db.enrollments       TO 'role_app_rw';
GRANT SELECT, INSERT, UPDATE, DELETE ON attendance_db.sessions          TO 'role_app_rw';
GRANT SELECT, INSERT, UPDATE, DELETE ON attendance_db.attendance        TO 'role_app_rw';
GRANT SELECT, INSERT, UPDATE         ON attendance_db.override_requests TO 'role_app_rw';
GRANT SELECT, INSERT, UPDATE         ON attendance_db.saga_log          TO 'role_app_rw';
GRANT SELECT, UPDATE                 ON attendance_db.app_meta          TO 'role_app_rw';
GRANT SELECT                         ON attendance_db.branches          TO 'role_app_rw';
GRANT SELECT                         ON attendance_db.divisions         TO 'role_app_rw';
GRANT SELECT                         ON attendance_db.audit_log         TO 'role_app_rw';
GRANT SELECT ON attendance_db.v_student_course_attendance TO 'role_app_rw';
GRANT SELECT ON attendance_db.v_student_attendance_pct    TO 'role_app_rw';
GRANT SELECT ON attendance_db.v_session_summary           TO 'role_app_rw';
GRANT SELECT ON attendance_db.v_course_summary            TO 'role_app_rw';
GRANT SELECT ON attendance_db.v_shortage_list             TO 'role_app_rw';
GRANT EXECUTE ON attendance_db.*                          TO 'role_app_rw';

-- ---------------- reporting role (views only) ----------------
GRANT SELECT ON attendance_db.v_student_course_attendance TO 'role_reporting_ro';
GRANT SELECT ON attendance_db.v_student_attendance_pct    TO 'role_reporting_ro';
GRANT SELECT ON attendance_db.v_session_summary           TO 'role_reporting_ro';
GRANT SELECT ON attendance_db.v_course_summary            TO 'role_reporting_ro';
GRANT SELECT ON attendance_db.v_shortage_list             TO 'role_reporting_ro';

-- ---------------- DBA role ----------------
GRANT ALL PRIVILEGES ON attendance_db.*   TO 'role_dba';
GRANT ALL PRIVILEGES ON attendance_test.* TO 'role_dba';

-- ---------------- users ----------------
CREATE USER IF NOT EXISTS '${MYSQL_APP_USER}'@'%' IDENTIFIED BY '${MYSQL_APP_PASSWORD}';
GRANT 'role_app_rw' TO '${MYSQL_APP_USER}'@'%';
SET DEFAULT ROLE 'role_app_rw' TO '${MYSQL_APP_USER}'@'%';
-- the test schema is disposable: full rights so pytest can clean up
GRANT ALL PRIVILEGES ON attendance_test.* TO '${MYSQL_APP_USER}'@'%';

CREATE USER IF NOT EXISTS '${MYSQL_ADMIN_USER}'@'%' IDENTIFIED BY '${MYSQL_ADMIN_PASSWORD}';
GRANT 'role_dba' TO '${MYSQL_ADMIN_USER}'@'%';
SET DEFAULT ROLE 'role_dba' TO '${MYSQL_ADMIN_USER}'@'%';

CREATE USER IF NOT EXISTS '${MYSQL_REPORT_USER}'@'%' IDENTIFIED BY '${MYSQL_REPORT_PASSWORD}';
GRANT 'role_reporting_ro' TO '${MYSQL_REPORT_USER}'@'%';
SET DEFAULT ROLE 'role_reporting_ro' TO '${MYSQL_REPORT_USER}'@'%';

FLUSH PRIVILEGES;
EOSQL

echo "[03_roles] done"
