# Database reference

Companion to the README. MySQL objects are defined in `db/mysql/01_schema.sql`; MongoDB collections in
`db/mongo/init-mongo.js` (and re-applied by `backend/app/db/mongo_schema.py`).

## MySQL objects at a glance

| Kind | Name | Notes |
|---|---|---|
| Table | `app_meta` | key/value: `schema_version`, `shortage_threshold` |
| Table | `branches`, `divisions` | lookup; `divisions UNIQUE (branch_id, year_of_study, name)` |
| Table | `students` | PK `prn`; UNIQUE email, UNIQUE (division_id, roll_no); CHECK consent, PRN/e-mail/phone format |
| Table | `teachers`, `users` | users: UNIQUE username, UNIQUE prn, UNIQUE teacher_id; bcrypt hash; lockout columns |
| Table | `courses`, `enrollments` | enrollments: composite PK (prn, course_id) |
| Table | `sessions` | UNIQUE (course_id, session_date, start_time); status SCHEDULED/OPEN/CLOSED/CANCELLED |
| Table | `attendance` | UNIQUE (session_id, prn); status PRESENT/LATE/ABSENT; method FACE_GROUP/FACE_SOLO/FACE_LIVE/QR/MANUAL/AUTO |
| Table | `override_requests` | PENDING/APPROVED/REJECTED; CHECK reason length, review consistency |
| Table | `audit_log` | append-only, JSON old/new values, no FK on purpose |
| Table | `saga_log` | saga state machine, JSON steps |
| View | `v_student_course_attendance` | per student x course: held, present, late, absent, pct |
| View | `v_student_attendance_pct` | per student overall + `is_shortage` |
| View | `v_session_summary` | per session counts and enrolled |
| View | `v_course_summary` | per course: enrolled, held, average pct, shortage count |
| View | `v_shortage_list` | rows below the threshold (per course) |
| Procedure | `mark_attendance`, `mark_late`, `open_session`, `close_session`, `auto_close_expired_sessions`, `apply_override`, `get_student_report`, `forget_student` | see README section 5 |
| Trigger | `trg_attendance_bi/bu/ai/au/ad`, `trg_users_bi/bu`, `trg_students_au/ad`, `trg_override_au` | late minutes, audit, role consistency |

Machine-readable errors raised by procedures (`SIGNAL SQLSTATE '45000'`):
`SESSION_NOT_FOUND`, `SESSION_NOT_OPEN`, `STUDENT_NOT_ENROLLED`, `ALREADY_MARKED:<status>`,
`OUTSIDE_SESSION_WINDOW`, `INVALID_SESSION_STATE`, `OVERRIDE_NOT_FOUND`, `OVERRIDE_ALREADY_RESOLVED`,
`STUDENT_NOT_FOUND`, `USER_ROLE_LINK_INVALID`. `app/core/errors.py` maps them to HTTP 404/409/400.

### Useful queries

```sql
-- one student's full report (3 result sets)
CALL get_student_report('12310005');

-- who is below 75 % in DBMS
SELECT prn, full_name, attendance_pct FROM v_shortage_list WHERE course_code = 'CS2201';

-- mark a whole class atomically (what the API does)
START TRANSACTION;
CALL mark_attendance(9, '12310001', 'FACE_GROUP', 0.71, NULL, @r1);
CALL mark_attendance(9, '12310002', 'FACE_GROUP', 0.66, NULL, @r2);
COMMIT;            -- or ROLLBACK if any call signalled an error
SELECT @r1, @r2;   -- INSERTED | DUPLICATE

-- audit trail of manual changes, newest first
SELECT changed_at, action, record_id, reason, JSON_EXTRACT(new_values, '$.status') AS new_status
  FROM audit_log WHERE table_name = 'attendance' ORDER BY audit_id DESC LIMIT 20;
```

---

## MongoDB collections

All timestamps are UTC BSON dates. Numbers written by the API are plain doubles/ints (numpy types are converted).

### face_embeddings

Many encrypted templates per student; linked to MySQL by `prn`.

| Field | Type | Notes |
|---|---|---|
| `prn` | string `^[A-Z0-9]{6,20}$` | cross-database key |
| `model` | string | `insightface-buffalo_l`, `dlib-resnet-128`, `opencv-haar-lbp-512`, `synthetic-512` |
| `dim` | int | 512 or 128 |
| `embedding_enc` | binData | Fernet token of little-endian float32 vector |
| `pose`, `yaw` | string, double | `front`/`left`/`right`/`up`/`down` |
| `quality` | object | brightness, contrast, sharpness, face_px, det_score, moire, glare |
| `source` | enum | REGISTRATION, ADD_PHOTOS, AUTO_REENROLL, REVIEW, SYNTHETIC |
| `active` | bool | false while a delete saga is in progress |
| `saga_id` | string | saga that created it (compensation deletes by this) |
| `pending_delete` | string | saga that soft-deleted it |

Indexes: `{prn: 1, created_at: -1}`, `{model: 1, active: 1}`, `{saga_id: 1}` (sparse).

```json
{
  "prn": "12310005", "model": "insightface-buffalo_l", "dim": 512,
  "embedding_enc": {"$binary": {"base64": "gAAAAABnEMKx...", "subType": "00"}},
  "pose": "right", "yaw": 18.7,
  "quality": {"brightness": 131.2, "contrast": 41.7, "sharpness": 68.0, "face_px": 236, "det_score": 0.89, "moire": 1.16, "glare": 0.0},
  "source": "REGISTRATION", "active": true, "saga_id": "80622c29-eb12-49ed-a20e-6e0c63f24338",
  "created_at": {"$date": "2026-10-19T10:39:44.201Z"}
}
```

### recognition_logs (TTL 90 days)

One document per detected face (group photo, late entry, live feed).

```json
{
  "kind": "GROUP", "session_id": 9, "draft_id": "6ad5f8492528d5ad74d364ec", "face_index": 3,
  "prn": "E2E00004", "confidence": 0.9872, "status": "MATCHED", "latency_ms": 800.7, "committed": true,
  "created_at": {"$date": "2026-10-19T11:05:21.004Z"}
}
```

`status` is one of MATCHED, LOW_CONFIDENCE, POSSIBLE, UNKNOWN, SPOOF_SUSPECTED, TOO_SMALL.
Indexes: `{prn: 1, created_at: -1}`, `{session_id: 1}`, `{status: 1, created_at: -1}`, TTL `{created_at: 1}`.
After a normal delete the PRN is replaced by `subject_hash` (pseudonymised statistics); after forget-me the
documents are deleted.

### snapshots (TTL 30 days)

```json
{"kind": "GROUP_ANNOTATED", "image": {"$binary": "/9j/4AAQ...", "$type": "00"}, "content_type": "image/jpeg",
 "session_id": 9, "prn": null, "meta": {"faces": 6}, "created_at": {"$date": "2026-10-19T11:05:20Z"}}
```

Kinds: GROUP_ANNOTATED, UNKNOWN_FACE, SPOOF, LATE, REVIEW_FACE.

### attendance_drafts (TTL on `expires_at`)

State between "analyse photo" and "confirm". `status` moves OPEN -> COMMITTING -> COMMITTED with an atomic
`find_one_and_update({status: "OPEN"})`, which is what blocks double submission.

```json
{
  "session_id": 9, "course_id": 1, "kind": "GROUP", "created_by": 2, "threshold": 0.45, "snapshot_id": "6ad5f849...",
  "candidates": {"E2E00002": {"confidence": 0.9838, "status": "MATCHED", "face_index": 1}},
  "faces": [{"face_index": 0, "bbox": [412, 286, 487, 383], "prn": null, "confidence": null, "status": "UNKNOWN",
             "suggestions": [], "embedding_enc": null, "crop": null}],
  "status": "COMMITTED", "result": {"inserted": 5, "duplicates": []},
  "created_at": {"$date": "2026-10-19T11:05:20Z"}, "expires_at": {"$date": "2026-10-19T23:05:20Z"}
}
```

### notifications (TTL 180 days)

```json
{"type": "LATE", "title": "Marked late", "message": "You were marked LATE by 14 min for CS2201 on 2026-10-19 09:00.",
 "recipient_prn": "12310005", "recipient_user_id": null, "audience_role": null,
 "data": {"session_id": 9, "late_minutes": 14}, "channel": "in_app", "read_by": [],
 "created_at": {"$date": "2026-10-19T03:44:02Z"}}
```

Types: LATE, SHORTAGE, UNKNOWN_FACE, SPOOF, REENROLL, OVERRIDE, SESSION, SYSTEM, DAILY_SUMMARY, REVIEW, ATTENDANCE.
A notification targets a student (`recipient_prn`), a user (`recipient_user_id`) or a role (`audience_role`).

### spoof_attempts

```json
{"endpoint": "/attendance/late", "reasons": ["STATIC_IMAGE", "NO_BLINK"], "prn": "12310005", "session_id": 9,
 "metrics": {"frames_used": 6, "identity_min_sim": 1.0, "motion": 0.0, "ear_min": 0.29, "ear_max": 0.29, "moire": 1.15, "glare": 0.0},
 "snapshot_id": "6ad5f84a...", "actor_id": 2, "client_ip": "172.18.0.6", "created_at": {"$date": "2026-10-19T11:06:02Z"}}
```

### review_queue

```json
{"session_id": 9, "prn": "12310007", "confidence": 0.41, "match_status": "POSSIBLE",
 "embedding_enc": {"$binary": "gAAAAAB...", "$type": "00"}, "snapshot_id": "6ad5f84b...", "source": "GROUP",
 "suggestions": [{"prn": "12310007", "score": 0.41}, {"prn": "12310011", "score": 0.29}],
 "status": "PENDING", "created_by": 2, "created_at": {"$date": "2026-10-19T11:05:31Z"}}
```

### liveness_nonces, meta

`{"nonce": "q3V9...", "created_at": ...}` with a UNIQUE index (replay protection) and a 10 minute TTL;
`{"_id": "embedding_index", "version": 42}` incremented whenever templates change.

---

## Aggregation pipelines

### Low-confidence matches per student

```js
db.recognition_logs.aggregate([
  { $match: { created_at: { $gte: since }, prn: { $ne: null }, confidence: { $gte: 0.37, $lt: 0.53 } } },
  { $group: { _id: "$prn", occurrences: { $sum: 1 }, avg_confidence: { $avg: "$confidence" },
              min_confidence: { $min: "$confidence" }, last_seen: { $max: "$created_at" },
              sessions: { $addToSet: "$session_id" } } },
  { $sort: { occurrences: -1, avg_confidence: 1 } },
  { $limit: 20 },
  { $project: { _id: 0, prn: "$_id", occurrences: 1, avg_confidence: { $round: ["$avg_confidence", 3] },
                min_confidence: { $round: ["$min_confidence", 3] }, last_seen: 1, session_count: { $size: "$sessions" } } }
])
```

### Daily recognition statistics

```js
db.recognition_logs.aggregate([
  { $match: { created_at: { $gte: since } } },
  { $group: {
      _id: { $dateToString: { format: "%Y-%m-%d", date: "$created_at", timezone: "Asia/Kolkata" } },
      faces: { $sum: 1 },
      matched: { $sum: { $cond: [{ $eq: ["$status", "MATCHED"] }, 1, 0] } },
      low_confidence: { $sum: { $cond: [{ $in: ["$status", ["LOW_CONFIDENCE", "POSSIBLE"]] }, 1, 0] } },
      unknown: { $sum: { $cond: [{ $in: ["$status", ["UNKNOWN", "TOO_SMALL"]] }, 1, 0] } },
      avg_confidence: { $avg: "$confidence" }, avg_latency_ms: { $avg: "$latency_ms" } } },
  { $sort: { _id: 1 } }
])
```

### Spoof attempts per day with reasons

```js
db.spoof_attempts.aggregate([
  { $match: { created_at: { $gte: since } } },
  { $project: { day: { $dateToString: { format: "%Y-%m-%d", date: "$created_at", timezone: "Asia/Kolkata" } }, reasons: 1 } },
  { $facet: {
      totals:  [ { $group: { _id: "$day", attempts: { $sum: 1 } } } ],
      reasons: [ { $unwind: "$reasons" }, { $group: { _id: { day: "$day", reason: "$reasons" }, n: { $sum: 1 } } } ] } }
])
```

Ready-to-run versions: [mongo/aggregations.js](mongo/aggregations.js).
