"""Synthetic data generator for demos, analytics and load tests.

Creates (all PRNs start with "SYN" so they can be purged):
  * N students in one division, enrolled in the courses of their branch/year
  * past CLOSED sessions over D days with realistic attendance patterns
    (per-student propensity, Monday dip, first-slot lateness)
  * encrypted synthetic face embeddings in MongoDB (model "synthetic-512",
    never used for matching real faces)
  * recognition logs, spoof attempts and notifications for the dashboards

Usage (inside the backend container):
    python -m scripts.generate_synthetic_data --students 200 --days 30
    python -m scripts.generate_synthetic_data --purge
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import random
import sys

import numpy as np
from sqlalchemy import text

from app.core.security import hash_password
from app.core.utils import utcnow
from app.db.mongo import C, col
from app.db.mysql import fetch_all, fetch_one, fetch_scalar, transaction
from app.repositories import embeddings as emb_repo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("synthetic")

FIRST = ["Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan", "Shaurya",
         "Ananya", "Diya", "Saanvi", "Aadhya", "Kavya", "Myra", "Anika", "Pari", "Riya", "Sara", "Omkar", "Tanvi",
         "Yash", "Sneha", "Pranav", "Gauri", "Atharva", "Rutuja", "Kunal", "Pooja"]
LAST = ["Patil", "Kulkarni", "Joshi", "Deshpande", "Shinde", "Pawar", "Jadhav", "Gokhale", "More", "Bhosale",
        "Chavan", "Gaikwad", "Kale", "Apte", "Naik", "Salunkhe", "Mane", "Thorat", "Wagh", "Bapat"]
SLOTS = ["08:00", "09:00", "10:15", "11:15", "13:30", "14:30", "15:30"]
DIM = 512


def unit(rng: np.random.Generator) -> np.ndarray:
    v = rng.standard_normal(DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def purge() -> None:
    with transaction() as conn:
        sessions = fetch_scalar(conn, "SELECT COUNT(*) FROM sessions WHERE topic LIKE 'SYN %%'")
        conn.execute(text("DELETE FROM sessions WHERE topic LIKE 'SYN %%'"))
        n = conn.execute(text("DELETE FROM students WHERE prn LIKE 'SYN%%'")).rowcount
    removed = {
        "face_embeddings": col(C.FACE_EMBEDDINGS).delete_many({"prn": {"$regex": "^SYN"}}).deleted_count,
        "recognition_logs": col(C.RECOGNITION_LOGS).delete_many({"synthetic": True}).deleted_count,
        "spoof_attempts": col(C.SPOOF_ATTEMPTS).delete_many({"synthetic": True}).deleted_count,
        "notifications": col(C.NOTIFICATIONS).delete_many({"data.synthetic": True}).deleted_count,
    }
    emb_repo.bump_index_version()
    log.info("Purged %d students, %d sessions, mongo=%s", n, sessions, removed)


def generate(students: int, days: int, embeddings_per_student: int, branch: str, year: int, division: str,
             seed: int) -> None:
    rng = np.random.default_rng(seed)
    random.seed(seed)
    with transaction() as conn:
        div = fetch_one(conn, """SELECT d.division_id, d.branch_id FROM divisions d JOIN branches b ON b.branch_id = d.branch_id
                                 WHERE b.code = :b AND d.year_of_study = :y AND d.name = :n""",
                        {"b": branch, "y": year, "n": division})
        if not div:
            sys.exit(f"Division {branch}-{year}-{division} does not exist")
        courses = fetch_all(conn, "SELECT course_id, code, teacher_id FROM courses WHERE branch_id = :b AND year_of_study = :y",
                            {"b": div["branch_id"], "y": year})
        if not courses:
            sys.exit("No courses for that branch/year - seed courses first")
        start_index = int(fetch_scalar(conn, "SELECT COUNT(*) FROM students WHERE prn LIKE 'SYN%%'") or 0)
        used_rolls = {r["roll_no"] for r in fetch_all(conn, "SELECT roll_no FROM students WHERE division_id = :d",
                                                      {"d": div["division_id"]})}
        rolls = [r for r in range(1, 301) if r not in used_rolls][:students]
        if len(rolls) < students:
            sys.exit(f"Only {len(rolls)} free roll numbers left in this division")

        pw_hash = hash_password("Synthetic123", rounds=8)
        people = []
        for i, roll in enumerate(rolls):
            prn = f"SYN{start_index + i + 1:07d}"
            name = f"{random.choice(FIRST)} {random.choice(LAST)}"
            propensity = float(np.clip(rng.beta(8, 2), 0.35, 0.99))  # most students attend ~80%
            people.append({"prn": prn, "name": name, "roll": roll, "p": propensity})
            conn.execute(text("""INSERT INTO students (prn, full_name, email, phone, division_id, roll_no, consent_given, face_status)
                                 VALUES (:p, :n, :e, :ph, :d, :r, TRUE, 'ENROLLED')"""),
                         {"p": prn, "n": name, "e": f"{prn.lower()}@synthetic.example.org", "ph": f"98{rng.integers(10**7, 10**8)}",
                          "d": div["division_id"], "r": roll})
            conn.execute(text("INSERT INTO users (username, password_hash, role, prn) VALUES (:p, :h, 'STUDENT', :p)"),
                         {"p": prn, "h": pw_hash})
            for c in courses:
                conn.execute(text("INSERT INTO enrollments (prn, course_id) VALUES (:p, :c)"), {"p": prn, "c": c["course_id"]})
        log.info("Inserted %d students", len(people))

        today = fetch_scalar(conn, "SELECT CURDATE()")
        session_rows = []
        for back in range(days, 0, -1):
            day = today - dt.timedelta(days=back)
            if day.weekday() == 6:  # no lectures on Sunday
                continue
            for c in courses:
                if rng.random() < 0.45:
                    continue
                slot = random.choice(SLOTS)
                start = dt.datetime.combine(day, dt.time.fromisoformat(slot))
                exists = fetch_scalar(conn, "SELECT COUNT(*) FROM sessions WHERE course_id = :c AND session_date = :d AND start_time = :t",
                                      {"c": c["course_id"], "d": day, "t": start.time()})
                if exists:
                    continue
                res = conn.execute(text("""
                    INSERT INTO sessions (course_id, teacher_id, session_date, start_time, end_time, late_after_min, status,
                                          opened_at, closed_at, room, topic)
                    VALUES (:c, :t, :d, :s, :e, 10, 'CLOSED', :o, :x, 'SYN-LAB', :topic)"""),
                                   {"c": c["course_id"], "t": c["teacher_id"], "d": day, "s": start.time(),
                                    "e": (start + dt.timedelta(hours=1)).time(), "o": start - dt.timedelta(minutes=3),
                                    "x": start + dt.timedelta(minutes=62), "topic": f"SYN lecture {c['code']}"})
                session_rows.append((int(res.lastrowid), start, c["code"]))

        # every student enrolled in the course gets a mark (otherwise the views would count the
        # already-seeded students as absent in these extra lectures)
        propensity = {p["prn"]: p["p"] for p in people}
        rosters = {c["code"]: [r["prn"] for r in fetch_all(conn, "SELECT prn FROM enrollments WHERE course_id = :c",
                                                           {"c": c["course_id"]})] for c in courses}
        records = 0
        logs: list[dict] = []
        for sid, start, code in session_rows:
            monday = 0.08 if start.weekday() == 0 else 0.0
            early = 0.10 if start.hour <= 8 else 0.0
            for prn in rosters[code]:
                person = {"prn": prn, "p": propensity.get(prn, 0.85)}
                r = rng.random()
                if r < person["p"] - monday:
                    late = rng.random() < 0.08 + early
                    status = "LATE" if late else "PRESENT"
                    minutes = int(rng.integers(11, 35)) if late else int(rng.integers(0, 6))
                    conf = float(np.clip(rng.normal(0.68, 0.08), 0.46, 0.95))
                    method = "FACE_SOLO" if late else "FACE_GROUP"
                else:
                    status, minutes, conf, method = "ABSENT", 0, None, "AUTO"
                conn.execute(text("""INSERT INTO attendance (session_id, prn, status, method, confidence, marked_at)
                                     VALUES (:s, :p, :st, :m, :c, :at)"""),
                             {"s": sid, "p": person["prn"], "st": status, "m": method,
                              "c": round(conf, 4) if conf is not None else None, "at": start + dt.timedelta(minutes=minutes)})
                records += 1
                if conf is not None:
                    logs.append({"kind": "GROUP" if method == "FACE_GROUP" else "SOLO", "session_id": sid,
                                 "prn": person["prn"], "confidence": conf,
                                 "status": "MATCHED" if conf >= 0.53 else "LOW_CONFIDENCE",
                                 "latency_ms": float(rng.normal(420, 60)), "synthetic": True,
                                 "created_at": (start + dt.timedelta(minutes=minutes)).astimezone(dt.timezone.utc)})
            for _ in range(int(rng.integers(0, 3))):  # unknown faces (visitors, other divisions)
                logs.append({"kind": "GROUP", "session_id": sid, "prn": None, "confidence": None, "status": "UNKNOWN",
                             "latency_ms": 400.0, "synthetic": True, "created_at": start.astimezone(dt.timezone.utc)})
        log.info("Inserted %d sessions and %d attendance rows", len(session_rows), records)

    # ---------------- MongoDB ----------------
    docs = []
    for person in people:
        base = unit(rng)
        for k in range(embeddings_per_student):
            noise = unit(rng)
            vec = 0.85 * base + 0.53 * noise
            docs.append(emb_repo.build_doc(prn=person["prn"], vector=vec / np.linalg.norm(vec), model="synthetic-512",
                                           source="SYNTHETIC", pose=["front", "left", "right"][k % 3],
                                           yaw=[0.0, -18.0, 18.0][k % 3]))
    for i in range(0, len(docs), 1000):
        emb_repo.insert_many(docs[i:i + 1000])
    if logs:
        col(C.RECOGNITION_LOGS).insert_many(logs, ordered=False)

    reasons = [["STATIC_IMAGE", "NO_HEAD_TURN"], ["SCREEN_ARTIFACTS"], ["NO_BLINK", "STATIC_IMAGE"], ["IDENTITY_CHANGED"]]
    spoofs = []
    for back in range(days):
        for _ in range(int(rng.poisson(0.7))):
            when = utcnow() - dt.timedelta(days=back, hours=int(rng.integers(0, 8)))
            spoofs.append({"endpoint": "/attendance/late", "reasons": random.choice(reasons),
                           "prn": random.choice(people)["prn"], "session_id": None, "metrics": {},
                           "synthetic": True, "created_at": when})
    if spoofs:
        col(C.SPOOF_ATTEMPTS).insert_many(spoofs)
    col(C.NOTIFICATIONS).insert_one({"type": "SYSTEM", "title": "Synthetic data loaded",
                                     "message": f"{len(people)} students, {len(session_rows)} sessions, {len(docs)} embeddings.",
                                     "audience_role": "ADMIN", "recipient_prn": None, "recipient_user_id": None,
                                     "read_by": [], "data": {"synthetic": True}, "created_at": utcnow()})
    emb_repo.bump_index_version()
    log.info("MongoDB: %d embeddings, %d recognition logs, %d spoof attempts", len(docs), len(logs), len(spoofs))
    log.info("Synthetic students can sign in with their PRN and password 'Synthetic123'")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--students", type=int, default=60)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--embeddings-per-student", type=int, default=5)
    parser.add_argument("--branch", default="CS")
    parser.add_argument("--year", type=int, default=2)
    parser.add_argument("--division", default="B")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--purge", action="store_true", help="remove all synthetic data")
    args = parser.parse_args()
    if args.purge:
        purge()
    else:
        generate(args.students, args.days, args.embeddings_per_student, args.branch.upper(), args.year,
                 args.division.upper(), args.seed)


if __name__ == "__main__":
    main()
