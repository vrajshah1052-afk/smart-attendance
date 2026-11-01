"""Create the MySQL schema, seed data, test schema and least-privilege users on a
local (non-Docker) MySQL server - the same steps the mysql image runs from
db/mysql/01_schema.sql, 02_seed.sql and 03_roles.sh.

usage:  python local/setup_db.py            (skips schema if attendance_db exists)
        python local/setup_db.py --reset    (drops attendance_db + attendance_test first)
        python local/setup_db.py --env-file .env.cloud   (managed MySQL, e.g. Aiven: no test schema)

Passwords come from the project .env (MYSQL_ROOT_PASSWORD = your local root password).
A cloud env file names the server instead: MYSQL_URI=mysql://avnadmin:<password>@<host>:<port>/defaultdb
(or MYSQL_HOST / MYSQL_PORT / MYSQL_ROOT_USER / MYSQL_ROOT_PASSWORD) plus the three
MYSQL_*_PASSWORD values of the users to create.
MongoDB needs no setup: the backend creates collections/indexes on start-up.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "db" / "mysql"


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def find_mysql() -> str:
    found = os.environ.get("MYSQL_EXE") or shutil.which("mysql")
    if not found:
        candidates = sorted(glob.glob(r"C:\Program Files\MySQL\MySQL Server *\bin\mysql.exe"))
        found = candidates[-1] if candidates else None
    if not found:
        sys.exit("mysql client not found - set MYSQL_EXE to the full path of mysql.exe")
    return found


def main() -> None:
    cloud = "--env-file" in sys.argv
    env = read_env(Path(sys.argv[sys.argv.index("--env-file") + 1]) if cloud else ROOT / ".env")
    if env.get("MYSQL_URI"):
        uri = urlsplit(env["MYSQL_URI"])
        env.update(MYSQL_HOST=uri.hostname or "", MYSQL_PORT=str(uri.port or 3306),
                   MYSQL_ROOT_USER=unquote(uri.username or ""), MYSQL_ROOT_PASSWORD=unquote(uri.password or ""))
    mysql = find_mysql()
    if cloud:  # the env file names the server; managed MySQL only accepts TLS
        host, port = env["MYSQL_HOST"], env.get("MYSQL_PORT", "3306")
    else:  # .env holds the Docker host name: default to the local server
        host, port = os.environ.get("MYSQL_HOST", "127.0.0.1"), os.environ.get("MYSQL_PORT", "3306")
    base = [mysql, f"-u{env.get('MYSQL_ROOT_USER') or 'root'}", "-h", host, "-P", port,
            "--default-character-set=utf8mb4"] + (["--ssl-mode=REQUIRED"] if cloud else [])
    proc_env = {**os.environ, "MYSQL_PWD": env["MYSQL_ROOT_PASSWORD"]}

    def run(sql: str, *extra: str) -> str:
        res = subprocess.run(base + list(extra), input=sql.encode("utf-8"), env=proc_env, capture_output=True)
        if res.returncode != 0:
            sys.exit(res.stderr.decode("utf-8", "replace").strip())
        return res.stdout.decode("utf-8", "replace")

    exists = run("SHOW DATABASES LIKE 'attendance_db';", "-N", "-B").strip() == "attendance_db"
    if "--reset" in sys.argv:
        print("dropping attendance_db and attendance_test")
        run("DROP DATABASE IF EXISTS attendance_db; DROP DATABASE IF EXISTS attendance_test;")
        exists = False

    if exists:
        print("attendance_db already exists - skipping schema/seed (use --reset to recreate)")
    else:
        schema = (SQL_DIR / "01_schema.sql").read_text(encoding="utf-8")
        print("loading 01_schema.sql")
        run(schema)
        print("loading 02_seed.sql")
        run((SQL_DIR / "02_seed.sql").read_text(encoding="utf-8"))
        if not cloud:
            print("creating pytest database attendance_test")
            run(schema.replace("attendance_db", "attendance_test"))

    # roles/users: reuse the SQL heredoc from 03_roles.sh so there is one source of truth
    roles_sh = (SQL_DIR / "03_roles.sh").read_text(encoding="utf-8")
    roles_sql = re.search(r"<<EOSQL\n(.*?)\nEOSQL", roles_sh, re.S).group(1)
    defaults = {"MYSQL_APP_USER": "attendance_app", "MYSQL_ADMIN_USER": "attendance_admin",
                "MYSQL_REPORT_USER": "attendance_report"}
    roles_sql = re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1)) or defaults.get(m.group(1), ""), roles_sql)
    # CREATE USER IF NOT EXISTS keeps an old password; re-sync it with .env on every run
    for kind in ("APP", "ADMIN", "REPORT"):
        user = env.get(f"MYSQL_{kind}_USER") or defaults[f"MYSQL_{kind}_USER"]
        roles_sql += f"\nALTER USER '{user}'@'%' IDENTIFIED BY '{env[f'MYSQL_{kind}_PASSWORD']}';"
    print("creating roles and users")
    run(roles_sql)
    print("done")


if __name__ == "__main__":
    main()
