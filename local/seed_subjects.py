"""Put the five SY subjects and their teachers into an existing database.

    backend\\.venv\\Scripts\\python.exe -I local\\seed_subjects.py
    backend\\.venv\\Scripts\\python.exe -I local\\seed_subjects.py --env-file .env.cloud

Idempotent, and it never drops anything. The three demo courses a database
seeded before this change still has (CS2201/CS2202/CS2203) are *renamed* onto
the first three subjects, so their sessions and attendance rows survive; the
two remaining subjects are inserted. The same goes for the four demo teachers:
they are renamed in place, so the sessions they already own keep a sensible
owner, and the fifth teacher is added.

Teachers sign in with their employee code (VIT@001), never an e-mail, and this
script is also what sets their password - a teacher can never register
themselves. Passwords follow firstname.employeecode in lower case.
"""
from __future__ import annotations

import pathlib
import ssl
import sys
from urllib.parse import unquote, urlsplit

import bcrypt
import pymysql

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (employee code, full name, subject code, subject name, credits, designation)
FACULTY = [
    ("VIT@001", "Renuka Vaidya", "DS", "Data Structures", 4, "Assistant Professor"),
    ("VIT@002", "Jyoti Yadav", "DBMS", "Database Management Systems", 4, "Associate Professor"),
    ("VIT@003", "Manisha More", "OOP", "Object Oriented Programming", 4, "Assistant Professor"),
    ("VIT@004", "Tejal Panmand", "DM", "Discrete Mathematics", 3, "Assistant Professor"),
    ("VIT@005", "Rahul Rathod", "LDM", "Logic Design and Microprocessors", 3, "Assistant Professor"),
]
YEAR_OF_STUDY = 2
SEMESTER = 3
BRANCH = "CS"

# demo course -> subject that takes its place (keeps sessions and attendance)
RENAME = {"CS2201": "DBMS", "CS2202": "DS", "CS2203": "OOP"}
# demo teacher -> the person who takes over their sessions
TEACHER_RENAME = {"VIT-CS-101": "VIT@002", "VIT-CS-102": "VIT@001",
                  "VIT-CS-103": "VIT@003", "VIT-IT-201": "VIT@004"}


def password_for(full_name: str, code: str) -> str:
    return f"{full_name.split()[0]}.{code}".lower()


def email_for(full_name: str) -> str:
    return ".".join(full_name.lower().split()) + "@vit.edu"


def read_env(path: pathlib.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def connect(env: dict[str, str], cloud: bool):
    if env.get("MYSQL_URI"):
        u = urlsplit(env["MYSQL_URI"])
        host, port = u.hostname, u.port or 3306
        user, password = unquote(u.username or ""), unquote(u.password or "")
    else:
        host, port = "127.0.0.1", int(env.get("MYSQL_PORT", "3306"))
        user, password = env.get("MYSQL_ROOT_USER", "root"), env["MYSQL_ROOT_PASSWORD"]
    kwargs = {"ssl": {"ssl": ssl.create_default_context()}} if cloud else {}
    return pymysql.connect(host=host, port=port, user=user, password=password,
                           database="attendance_db", autocommit=True, connect_timeout=30, **kwargs)


def main() -> None:
    cloud = "--env-file" in sys.argv
    env = read_env(pathlib.Path(sys.argv[sys.argv.index("--env-file") + 1]) if cloud else ROOT / ".env")
    rounds = int(env.get("BCRYPT_ROUNDS", "12"))
    conn = connect(env, cloud)
    cur = conn.cursor()

    cur.execute("SELECT branch_id FROM branches WHERE code = %s", (BRANCH,))
    row = cur.fetchone()
    if not row:
        sys.exit(f"branch {BRANCH} is missing - run local/setup_db.py first")
    branch_id = row[0]

    # ---- teachers: rename the demo ones in place, then upsert all five ----
    for old_code, new_code in TEACHER_RENAME.items():
        cur.execute("SELECT teacher_id FROM teachers WHERE employee_code = %s", (new_code,))
        if cur.fetchone():
            continue  # already renamed on an earlier run
        cur.execute("UPDATE teachers SET employee_code = %s WHERE employee_code = %s", (new_code, old_code))
        if cur.rowcount:
            print(f"  teacher {old_code} -> {new_code}")

    teacher_ids: dict[str, int] = {}
    for code, name, _subject, _subject_name, _credits, designation in FACULTY:
        email, pw_hash = email_for(name), bcrypt.hashpw(password_for(name, code).encode(), bcrypt.gensalt(rounds)).decode()
        cur.execute("SELECT teacher_id FROM teachers WHERE employee_code = %s", (code,))
        row = cur.fetchone()
        if row:
            teacher_id = row[0]
            cur.execute("UPDATE teachers SET full_name = %s, email = %s, branch_id = %s, designation = %s"
                        " WHERE teacher_id = %s", (name, email, branch_id, designation, teacher_id))
            print(f"  teacher {code} updated: {name}")
        else:
            cur.execute("INSERT INTO teachers (employee_code, full_name, email, branch_id, designation)"
                        " VALUES (%s, %s, %s, %s, %s)", (code, name, email, branch_id, designation))
            teacher_id = cur.lastrowid
            print(f"  teacher {code} created: {name}")
        teacher_ids[code] = teacher_id

        # the login: username is the employee code, password set here (admin-provisioned)
        cur.execute("SELECT user_id FROM users WHERE teacher_id = %s", (teacher_id,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE users SET username = %s, password_hash = %s, role = 'TEACHER',"
                        " is_active = 1, must_change_password = 0, failed_logins = 0, locked_until = NULL"
                        " WHERE user_id = %s", (code, pw_hash, row[0]))
        else:
            cur.execute("INSERT INTO users (username, password_hash, role, teacher_id, must_change_password)"
                        " VALUES (%s, %s, 'TEACHER', %s, 0)", (code, pw_hash, teacher_id))

    # ---- courses: rename the demo ones, then upsert all five ----
    for old_code, new_code in RENAME.items():
        cur.execute("SELECT course_id FROM courses WHERE code = %s", (new_code,))
        if cur.fetchone():
            continue
        cur.execute("UPDATE courses SET code = %s WHERE code = %s", (new_code, old_code))
        if cur.rowcount:
            print(f"  course {old_code} -> {new_code} (its sessions and attendance are kept)")

    for code, name, subject, subject_name, credits, _designation in FACULTY:
        teacher_id = teacher_ids[code]
        cur.execute("SELECT course_id FROM courses WHERE code = %s", (subject,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE courses SET name = %s, credits = %s, branch_id = %s, year_of_study = %s,"
                        " semester = %s, teacher_id = %s, is_active = 1 WHERE course_id = %s",
                        (subject_name, credits, branch_id, YEAR_OF_STUDY, SEMESTER, teacher_id, row[0]))
            print(f"  course {subject} updated: {subject_name} ({name}), semester {SEMESTER}")
        else:
            cur.execute("INSERT INTO courses (code, name, credits, branch_id, year_of_study, semester, teacher_id)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (subject, subject_name, credits, branch_id, YEAR_OF_STUDY, SEMESTER, teacher_id))
            print(f"  course {subject} created: {subject_name} ({name})")

    # sessions follow their course's coordinator where they had the old demo owner
    for code, _name, subject, *_rest in FACULTY:
        cur.execute("UPDATE sessions s JOIN courses c ON c.course_id = s.course_id"
                    " SET s.teacher_id = c.teacher_id WHERE c.code = %s AND s.teacher_id <> c.teacher_id",
                    (subject,))

    # every SY CS student takes every one of the five subjects
    cur.execute("""
        INSERT IGNORE INTO enrollments (prn, course_id)
        SELECT s.prn, c.course_id
          FROM students s
          JOIN divisions d ON d.division_id = s.division_id
          JOIN courses c ON c.branch_id = d.branch_id AND c.year_of_study = d.year_of_study
         WHERE c.semester = %s""", (SEMESTER,))
    if cur.rowcount:
        print(f"  {cur.rowcount} enrolments added")

    print()
    print("  code      teacher           subject   password")
    for code, name, subject, *_rest in FACULTY:
        print(f"  {code}   {name:17} {subject:9} {password_for(name, code)}")

    cur.close()
    conn.close()
    print("\ndone")


if __name__ == "__main__":
    main()
