"""Print what is stored in both databases, as plain-text tables for the Command Prompt.

usage:  local\\show-data.cmd                  tables + faces + MongoDB summary
        local\\show-data.cmd --only faces     one section (tables | faces | mongo)
        local\\show-data.cmd --export         also save stored photos (snapshots) as JPEGs
                                             into local\\face_snapshots and open the folder
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections import defaultdict
from decimal import Decimal

import numpy as np
import pymysql
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pymongo import MongoClient

from setup_db import ROOT, read_env

EXPORT_DIR = ROOT / "local" / "face_snapshots"


# ------------------------------------------------------------------ output
def fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return str(int(value))
    if isinstance(value, (float, Decimal)):
        return f"{float(value):.3f}"
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "..."


def table(rows: list[dict], cols: list[str] | None = None) -> None:
    if not rows:
        print("   (none)")
        return
    cols = cols or list(rows[0])
    cells = [[fmt(r.get(c)) for c in cols] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    print("   " + "  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("   " + "  ".join("-" * w for w in widths))
    for row in cells:
        print("   " + "  ".join(v.ljust(w) for v, w in zip(row, widths)))


def heading(text: str) -> None:
    print("\n" + "=" * 100 + f"\n {text}\n" + "=" * 100)


def local_time(value: dt.datetime | None) -> dt.datetime | None:
    """MongoDB stores UTC; MySQL already holds local time."""
    return value.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None) if value else None


# ------------------------------------------------------------------ sections
def show_tables(cur) -> None:
    heading("MySQL  attendance_db  -  tables and views")
    cur.execute("SELECT table_name AS t, table_type AS k FROM information_schema.tables "
                "WHERE table_schema = 'attendance_db' ORDER BY table_type, table_name")
    counts = []
    for row in cur.fetchall():
        cur.execute(f"SELECT COUNT(*) AS n FROM `{row['t']}`")
        counts.append({"name": row["t"], "type": "VIEW" if row["k"] == "VIEW" else "TABLE", "rows": cur.fetchone()["n"]})
    table(counts)

    print("\n -- students (latest 10)")
    cur.execute("SELECT s.prn, s.full_name, d.year_of_study AS year, d.name AS division, s.roll_no, s.face_status, "
                "s.created_at "
                "FROM students s JOIN divisions d ON d.division_id = s.division_id "
                "ORDER BY s.created_at DESC, s.prn LIMIT 10")
    table(cur.fetchall())

    print("\n -- attendance (latest 10)")
    cur.execute("SELECT a.session_id, c.code AS course, a.prn, s.full_name, a.status, a.method, "
                "a.confidence, a.late_minutes AS late_min, a.marked_at "
                "FROM attendance a JOIN students s ON s.prn = a.prn "
                "JOIN sessions se ON se.session_id = a.session_id JOIN courses c ON c.course_id = se.course_id "
                "ORDER BY a.marked_at DESC, a.attendance_id DESC LIMIT 10")
    table(cur.fetchall())

    print("\n -- attendance % per student (view v_student_attendance_pct, lowest 10)")
    cur.execute("SELECT prn, full_name, branch, division, total_sessions, present_count, late_count, absent_count, "
                "attendance_pct FROM v_student_attendance_pct ORDER BY attendance_pct LIMIT 10")
    table(cur.fetchall())


def show_faces(db, names: dict[str, str], cipher: MultiFernet | None) -> None:
    heading("FACES  -  MongoDB face_embeddings (one encrypted face vector per registration photo)")
    per_prn: dict[str, list[dict]] = defaultdict(list)
    for doc in db.face_embeddings.find({"active": True}).sort("created_at", 1):
        per_prn[doc["prn"]].append(doc)
    rows = []
    for prn, docs in per_prn.items():
        q = [d.get("quality") or {} for d in docs]
        rows.append({
            "prn": prn, "name": names.get(prn, "?"), "templates": len(docs), "model": docs[0]["model"],
            "dim": docs[0]["dim"], "poses": ",".join(sorted({d.get("pose") or "?" for d in docs})),
            "sharpness": float(np.mean([x.get("sharpness", 0) for x in q])),
            "face_px": float(np.mean([x.get("face_px", 0) for x in q])),
            "enrolled": local_time(docs[0]["created_at"]),
        })
    table(rows)
    if not per_prn:
        return

    print("\n -- what a stored face looks like (first template of each student, decrypted)")
    for prn, docs in per_prn.items():
        token = bytes(docs[0]["embedding_enc"])
        if cipher is None:
            print(f"   {prn}: {len(token)}-byte encrypted token (key not found, cannot decrypt)")
            continue
        try:
            vec = np.frombuffer(cipher.decrypt(token), dtype="<f4")
        except InvalidToken:
            print(f"   {prn}: {len(token)}-byte token - wrong key, cannot decrypt")
            continue
        head = " ".join(f"{v:+.3f}" for v in vec[:8])
        print(f"   {prn} {names.get(prn, '?'):<16} {len(token)} bytes encrypted -> {vec.size} numbers: [{head} ...]")

    print("\n -- how similar the enrolled faces are to each other (cosine of average vectors; same person ~1.0)")
    if cipher is not None and len(per_prn) > 1:
        cents = {}
        for prn, docs in per_prn.items():
            vecs = np.array([np.frombuffer(cipher.decrypt(bytes(d["embedding_enc"])), dtype="<f4") for d in docs])
            c = vecs.mean(axis=0)
            cents[prn] = c / np.linalg.norm(c)
        prns = list(cents)
        print("   " + " " * 12 + "".join(p.rjust(12) for p in prns))
        for a in prns:
            print("   " + a.ljust(12) + "".join(f"{float(cents[a] @ cents[b]):12.3f}" for b in prns))

    print("\n -- recognition results (latest 10, recognition_logs)")
    logs = list(db.recognition_logs.find({}, {"kind": 1, "session_id": 1, "prn": 1, "status": 1, "confidence": 1,
                                              "latency_ms": 1, "created_at": 1}).sort("created_at", -1).limit(10))
    table([{"time": local_time(d.get("created_at")), "kind": d.get("kind"), "session": d.get("session_id"),
            "prn": d.get("prn"), "name": names.get(d.get("prn") or "", "-"), "status": d.get("status"),
            "confidence": d.get("confidence"), "latency_ms": d.get("latency_ms")} for d in logs])


def show_mongo(db, export: bool) -> None:
    heading("MongoDB  attendance_logs  -  collections")
    table([{"collection": n, "documents": db[n].count_documents({})} for n in sorted(db.list_collection_names())])

    print("\n -- stored photos (snapshots: annotated group photos, unknown / spoof / late faces)")
    snaps = list(db.snapshots.find({}, {"image": 0}).sort("created_at", -1))
    table([{"id": str(s["_id"]), "kind": s.get("kind"), "session": s.get("session_id"), "prn": s.get("prn"),
            "faces": (s.get("meta") or {}).get("faces"), "time": local_time(s.get("created_at"))} for s in snaps])
    if export and snaps:
        EXPORT_DIR.mkdir(exist_ok=True)
        for s in db.snapshots.find({}, {"image": 1, "kind": 1, "created_at": 1}):
            stamp = local_time(s["created_at"]).strftime("%Y%m%d-%H%M%S")
            (EXPORT_DIR / f"{stamp}_{s.get('kind', 'IMG')}_{s['_id']}.jpg").write_bytes(bytes(s["image"]))
        print(f"\n   saved {len(snaps)} photos to {EXPORT_DIR}")
        os.startfile(EXPORT_DIR)
    elif snaps:
        print("\n   run  local\\show-faces.cmd  to save these photos as JPEG files and open them")


# ------------------------------------------------------------------ main
def load_cipher(env: dict[str, str]) -> MultiFernet | None:
    keys = env.get("EMBEDDING_ENC_KEY", "")
    if not keys:
        try:
            keys = json.loads((ROOT / "backend" / "data" / "secrets.json").read_text())["embedding_enc_key"]
        except (OSError, ValueError, KeyError):
            return None
    return MultiFernet([Fernet(k.strip().encode()) for k in keys.split(",") if k.strip()])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["tables", "faces", "mongo"])
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    env = read_env(ROOT / ".env")
    conn = pymysql.connect(host="127.0.0.1", port=3306, database="attendance_db",
                           user=env.get("MYSQL_ADMIN_USER") or "attendance_admin",
                           password=env["MYSQL_ADMIN_PASSWORD"], cursorclass=pymysql.cursors.DictCursor)
    db = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000)["attendance_logs"]
    with conn, conn.cursor() as cur:
        if args.only in (None, "tables"):
            show_tables(cur)
        if args.only in (None, "faces"):
            cur.execute("SELECT prn, full_name FROM students")
            names = {r["prn"]: r["full_name"] for r in cur.fetchall()}
            show_faces(db, names, load_cipher(env))
    if args.only in (None, "mongo") or args.export:
        show_mongo(db, args.export)


if __name__ == "__main__":
    main()
