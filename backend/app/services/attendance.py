"""Attendance flows: group photo (analyse -> confirm), solo late entry, QR fallback, live feed.

Source of truth is MySQL (ACID). MongoDB receives drafts, logs, snapshots and
notifications on a best-effort (BASE) basis: if MongoDB is down, attendance
still works and only the auxiliary data is skipped.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
from bson import Binary

from app.config import get_settings
from app.core.crypto import get_cipher
from app.core.deps import CurrentUser
from app.core.errors import AppError, bad_request, conflict, forbidden, not_found, unprocessable
from app.core.utils import local_today
from app.db.mysql import audit_context, transaction
from app.face.annotate import annotate
from app.face.imageio import crop_face, decode_data_url, decode_image, encode_jpeg, to_data_url
from app.face.liveness import evaluate_liveness
from app.face.quality import assess_face
from app.face.types import l2_normalize
from app.repositories import attendance as att_repo
from app.repositories import embeddings as emb_repo
from app.repositories import logs as logs_repo
from app.repositories import notifications as notif_repo
from app.repositories import sessions as sessions_repo
from app.repositories import students as students_repo
from app.services import face_service
from app.services.challenges import consume_challenge, verify_qr_code
from app.services.notify import event, notify
from app.services.recognition import match_faces, match_single
from app.ws.manager import ClientState

logger = logging.getLogger(__name__)

RECOGNISED = ("MATCHED", "LOW_CONFIDENCE")


# ------------------------------------------------------------------ helpers
def load_session(conn: Any, session_id: int) -> dict[str, Any]:
    session = sessions_repo.get_session(conn, session_id)
    if not session:
        raise not_found("Session not found", "SESSION_NOT_FOUND")
    return session


def assert_can_manage(conn: Any, session: dict[str, Any], user: CurrentUser) -> None:
    if user.is_admin:
        return
    if user.role == "TEACHER" and sessions_repo.can_manage(conn, session["session_id"], user.teacher_id):
        return
    raise forbidden("You can only take attendance for your own sessions")


def _require_open(session: dict[str, Any]) -> None:
    if session["status"] != "OPEN":
        raise conflict(f"Session is {session['status']}. Open it before taking attendance", "SESSION_NOT_OPEN")


def _session_label(session: dict[str, Any]) -> str:
    return f"{session['course_code']} on {session['session_date']} {session['start_time']}"


# ------------------------------------------------------------- group photo
def analyse_group(session_id: int, image_bytes: bytes, actor: CurrentUser,
                  threshold: float | None = None) -> dict[str, Any]:
    s = get_settings()
    with transaction() as conn:
        session = load_session(conn, session_id)
        assert_can_manage(conn, session, actor)
        _require_open(session)
        roster = students_repo.course_roster(conn, session["course_id"])
        existing = att_repo.statuses_for_session(conn, session_id)

    names = {r["prn"]: r["full_name"] for r in roster}
    candidates = {r["prn"] for r in roster if r["face_status"] != "PENDING"}
    img = decode_image(image_bytes, max_side=2400)
    t_used = float(threshold) if threshold is not None else face_service.match_threshold()
    margin = s.low_conf_margin

    started = time.perf_counter()
    faces = face_service.detect(img, max_faces=0)
    if not faces:
        raise unprocessable("No faces were detected. Check lighting / distance and retake the photo",
                            "NO_FACES_DETECTED")
    results = match_faces(img, faces, candidates, threshold=t_used, margin=margin, min_face_px=s.group_min_face_px)
    latency_ms = (time.perf_counter() - started) * 1000

    public_faces = [r.public(names) for r in results]
    annotated = encode_jpeg(annotate(img, [{k: v for k, v in f.items() if k != "crop"} for f in public_faces]), 82)
    snapshot_id = logs_repo.save_snapshot("GROUP_ANNOTATED", annotated, session_id=session_id,
                                          meta={"faces": len(results)})

    cipher = get_cipher()
    draft_faces = []
    for r in results:
        draft_faces.append({
            "face_index": r.face_index, "bbox": r.bbox, "prn": r.prn, "confidence": r.confidence,
            "status": r.status, "suggestions": r.suggestions,
            "embedding_enc": Binary(cipher.encrypt(r.embedding)) if r.embedding is not None
            and r.status in ("LOW_CONFIDENCE", "POSSIBLE") else None,
            "crop": Binary(r.crop_jpeg) if r.crop_jpeg and r.status in ("LOW_CONFIDENCE", "POSSIBLE") else None,
        })
    candidates_map = {r.prn: {"confidence": r.confidence, "status": r.status, "face_index": r.face_index}
                      for r in results if r.prn}
    draft_id = logs_repo.create_draft({
        "session_id": session_id, "course_id": session["course_id"], "kind": "GROUP",
        "created_by": actor.user_id, "threshold": t_used, "snapshot_id": snapshot_id,
        "candidates": candidates_map, "faces": draft_faces,
    })

    logs_repo.log_recognitions([{
        "kind": "GROUP", "session_id": session_id, "draft_id": draft_id, "face_index": r.face_index,
        "prn": r.prn, "confidence": r.confidence, "status": r.status, "latency_ms": latency_ms,
        "committed": False} for r in results])

    summary = {k: sum(1 for r in results if r.status == k)
               for k in ("MATCHED", "LOW_CONFIDENCE", "POSSIBLE", "UNKNOWN", "TOO_SMALL", "SPOOF_SUSPECTED")}
    summary["detected"] = len(results)

    if summary["UNKNOWN"] or summary["TOO_SMALL"]:
        notify("UNKNOWN_FACE", "Unknown faces in group photo",
               f"{summary['UNKNOWN'] + summary['TOO_SMALL']} face(s) could not be identified in "
               f"{_session_label(session)}.", recipient_user_id=actor.user_id,
               data={"session_id": session_id, "draft_id": draft_id, "snapshot_id": snapshot_id})
    for r in results:
        if r.status == "SPOOF_SUSPECTED":
            notif_repo.log_spoof(endpoint="/attendance/group", reasons=["SCREEN_ARTIFACTS"], prn=r.prn,
                                 session_id=session_id, metrics=r.spoof or {}, snapshot_id=snapshot_id,
                                 actor_id=actor.user_id, client_ip=None)
    if summary["SPOOF_SUSPECTED"]:
        notify("SPOOF", "Possible photo/screen spoof", f"{summary['SPOOF_SUSPECTED']} face(s) in "
               f"{_session_label(session)} look like a re-captured screen or print.", audience_role="ADMIN",
               data={"session_id": session_id})

    roster_out = []
    for row in roster:
        cand = candidates_map.get(row["prn"])
        roster_out.append({
            "prn": row["prn"], "full_name": row["full_name"], "roll_no": row["roll_no"], "division": row["division"],
            "face_status": row["face_status"], "already_marked": existing.get(row["prn"]),
            "detected": bool(cand and cand["status"] in RECOGNISED),
            "suggested": bool(cand and cand["status"] == "POSSIBLE"),
            "confidence": cand["confidence"] if cand else None,
        })
    event("group_analysed", {"session_id": session_id, "summary": summary})
    return {
        "draft_id": draft_id,
        "session": session,
        "threshold": t_used,
        "low_conf_margin": margin,
        "latency_ms": round(latency_ms, 1),
        "annotated_image": to_data_url(annotated),
        "faces": public_faces,
        "summary": summary,
        "roster": roster_out,
    }


def confirm_group(draft_id: str, session_id: int, prns: list[str], manual: list[dict[str, str]],
                  actor: CurrentUser) -> dict[str, Any]:
    """Teacher-confirmed list -> ONE MySQL transaction (all or nothing)."""
    draft = logs_repo.get_draft(draft_id)
    if not draft:
        raise not_found("Draft expired or not found - analyse the photo again", "DRAFT_NOT_FOUND")
    if int(draft["session_id"]) != session_id:
        raise bad_request("Draft belongs to another session", "DRAFT_SESSION_MISMATCH")
    if draft.get("status") == "COMMITTED":
        raise conflict("This attendance was already submitted", "ALREADY_COMMITTED", draft.get("result"))
    if not logs_repo.lock_draft(draft_id):
        raise conflict("This attendance is already being submitted", "ALREADY_COMMITTED")

    candidates: dict[str, Any] = draft.get("candidates") or {}
    method = "FACE_LIVE" if draft.get("kind") == "LIVE" else "FACE_GROUP"
    manual_prns = [m["prn"].strip().upper() for m in manual]
    inserted: list[str] = []
    duplicates: list[str] = []
    try:
        with transaction() as conn:
            session = load_session(conn, session_id)
            assert_can_manage(conn, session, actor)
            _require_open(session)
            enrolled = {r["prn"] for r in students_repo.course_roster(conn, session["course_id"])}
            invalid = sorted({p for p in prns + manual_prns if p not in enrolled})
            if invalid:
                raise bad_request(f"Not enrolled in {session['course_code']}: {', '.join(invalid)}",
                                  "STUDENT_NOT_ENROLLED", {"prns": invalid})
            not_recognised = [p for p in prns if (candidates.get(p) or {}).get("confidence") is None]
            if not_recognised:
                raise bad_request("These students were not recognised in the photo; add them as manual entries "
                                  f"with a reason: {', '.join(not_recognised)}", "NOT_RECOGNISED",
                                  {"prns": not_recognised})
            for prn in prns:
                result = att_repo.mark_present(conn, session_id, prn, method, candidates[prn]["confidence"],
                                               actor.user_id)
                (inserted if result == "INSERTED" else duplicates).append(prn)
            for item in manual:
                prn = item["prn"].strip().upper()
                if prn in prns:
                    continue
                with audit_context(conn, actor.user_id, f"Manual addition: {item['reason']}"):
                    result = att_repo.mark_present(conn, session_id, prn, "MANUAL", None, actor.user_id)
                (inserted if result == "INSERTED" else duplicates).append(prn)
    except Exception:
        logs_repo.unlock_draft(draft_id)
        raise

    result = {"session_id": session_id, "inserted": len(inserted), "duplicates": duplicates,
              "marked_prns": inserted, "manual": len(manual_prns), "draft_id": draft_id}
    logs_repo.finish_draft(draft_id, result)
    logs_repo.mark_logs_committed(draft_id, inserted)
    _queue_reviews_after_confirm(draft, set(prns) | set(manual_prns), actor)
    event("attendance_committed", {"session_id": session_id, "inserted": len(inserted),
                                   "course_code": session["course_code"]})
    logger.info("Session %s: %d marked present (%d duplicates) by user %s", session_id, len(inserted),
                len(duplicates), actor.user_id)
    return result


def _queue_reviews_after_confirm(draft: dict[str, Any], included: set[str], actor: CurrentUser) -> None:
    """Possible matches the teacher did NOT tick go to the low-confidence review queue."""
    for face in draft.get("faces") or []:
        if face.get("status") != "POSSIBLE" or not face.get("prn") or face["prn"] in included:
            continue
        snapshot_id = logs_repo.save_snapshot("REVIEW_FACE", bytes(face["crop"]), session_id=draft["session_id"],
                                              prn=face["prn"]) if face.get("crop") else None
        notif_repo.create_review(session_id=int(draft["session_id"]), prn=face["prn"],
                                 confidence=float(face["confidence"] or 0), status_hint="POSSIBLE",
                                 embedding_enc=bytes(face["embedding_enc"]) if face.get("embedding_enc") else None,
                                 snapshot_id=snapshot_id, source=draft.get("kind", "GROUP"),
                                 suggestions=face.get("suggestions") or [], created_by=actor.user_id)


# ------------------------------------------------------------- late entry
def late_entry(session_id: int, frames: list[bytes], challenge_token: str | None, actor: CurrentUser,
               client_ip: str | None = None) -> dict[str, Any]:
    s = get_settings()
    with transaction() as conn:
        session = load_session(conn, session_id)
        assert_can_manage(conn, session, actor)
        _require_open(session)
        roster = students_repo.course_roster(conn, session["course_id"])
    names = {r["prn"]: r["full_name"] for r in roster}
    candidates = {r["prn"] for r in roster if r["face_status"] != "PENDING"}

    if not frames:
        raise unprocessable("Capture at least one frame", "NO_FRAMES")
    if len(frames) > s.liveness_max_frames:
        raise unprocessable(f"Send at most {s.liveness_max_frames} frames", "TOO_MANY_FRAMES")
    challenge: str | None = None
    if s.liveness_required:
        if not challenge_token:
            raise AppError(400, "CHALLENGE_REQUIRED", "Request a liveness challenge first (GET /liveness/challenge)")
        challenge = consume_challenge(challenge_token, actor.user_id)
        if len(frames) < s.liveness_min_frames:
            raise unprocessable(f"Liveness needs at least {s.liveness_min_frames} frames", "NOT_ENOUGH_FRAMES")

    images = [decode_image(f, max_side=1280) for f in frames]
    started = time.perf_counter()
    faces_per = [face_service.detect(img, max_faces=0) for img in images]
    counts = [len(fs) for fs in faces_per]
    if any(c > 1 for c in counts):
        raise unprocessable("Multiple faces detected - only the late student may be in front of the camera",
                            "MULTIPLE_FACES", {"faces_per_frame": counts})
    single = [(i, fs[0]) for i, fs in enumerate(faces_per) if len(fs) == 1 and fs[0].embedding is not None]
    if not single:
        raise unprocessable("No face detected - face the camera in good light", "NO_FACE",
                            {"faces_per_frame": counts})

    best_i, best_face = max(single, key=lambda t: t[1].min_side * t[1].det_score)
    best_img = images[best_i]
    quality = assess_face(best_img, best_face, **face_service.quality_thresholds())
    if not quality.ok:
        details = quality.to_dict()
        raise unprocessable("; ".join(details["messages"]), "PHOTO_QUALITY", details)

    t_used, margin = face_service.match_threshold(), s.low_conf_margin
    probe = l2_normalize(np.mean(np.stack([f.embedding for _, f in single]), axis=0))
    best, status, top = match_single(probe, candidates, t_used, margin)

    liveness_out: dict[str, Any] | None = None
    if challenge:
        liveness = evaluate_liveness(
            images, faces_per, challenge, min_frames=s.liveness_min_frames,
            min_yaw_delta=s.liveness_min_yaw_delta, ear_closed=s.liveness_ear_closed,
            ear_drop_ratio=s.liveness_ear_drop_ratio, static_diff=s.liveness_static_diff,
            identity_threshold=t_used, moire_threshold=s.moire_threshold, glare_threshold=s.glare_threshold)
        liveness_out = liveness.to_dict()
        if not liveness.passed:
            claimed = best.prn if best and status in RECOGNISED else None
            snapshot_id = logs_repo.save_snapshot("SPOOF", encode_jpeg(best_img, 80), session_id=session_id,
                                                  prn=claimed, meta={"reasons": liveness.reasons})
            notif_repo.log_spoof(endpoint="/attendance/late", reasons=liveness.reasons, prn=claimed,
                                 session_id=session_id, metrics=liveness.metrics, snapshot_id=snapshot_id,
                                 actor_id=actor.user_id, client_ip=client_ip)
            notify("SPOOF", "Spoof attempt blocked",
                   f"Liveness failed during late entry for {_session_label(session)}: "
                   f"{', '.join(liveness.reasons)}", audience_role="ADMIN",
                   data={"session_id": session_id, "claimed_prn": claimed, "reasons": liveness.reasons})
            event("spoof_attempt", {"session_id": session_id, "reasons": liveness.reasons})
            raise AppError(403, "LIVENESS_FAILED", "Liveness check failed: " + "; ".join(liveness_out["messages"]),
                           liveness_out)

    latency_ms = (time.perf_counter() - started) * 1000
    if status not in RECOGNISED or best is None:
        review_id = None
        if status == "POSSIBLE" and best is not None:
            snapshot_id = logs_repo.save_snapshot("REVIEW_FACE", encode_jpeg(crop_face(best_img, best_face.bbox,
                                                                                       size=160)),
                                                  session_id=session_id, prn=best.prn)
            review_id = notif_repo.create_review(
                session_id=session_id, prn=best.prn, confidence=best.score, status_hint="POSSIBLE",
                embedding_enc=get_cipher().encrypt(probe), snapshot_id=snapshot_id, source="SOLO",
                suggestions=[{"prn": c.prn, "score": round(c.score, 4)} for c in top], created_by=actor.user_id)
        logs_repo.log_recognitions([{"kind": "SOLO", "session_id": session_id, "prn": best.prn if best else None,
                                     "confidence": best.score if best else None, "status": status,
                                     "latency_ms": latency_ms, "committed": False}])
        notify("UNKNOWN_FACE", "Unrecognised late entry",
               f"A face at the late-entry kiosk for {_session_label(session)} was not recognised.",
               recipient_user_id=actor.user_id, data={"session_id": session_id, "review_id": review_id})
        raise AppError(404, "UNKNOWN_FACE", "Face not recognised among students enrolled in this course"
                       + (" - sent to the review queue" if review_id else ""), {"review_id": review_id})

    with transaction() as conn:
        _, proc_result = att_repo.mark_late(conn, session_id, best.prn, "FACE_SOLO", best.score, actor.user_id)
        record = att_repo.get_record(conn, session_id, best.prn) or {}

    final_status = record.get("status", "LATE")
    late_minutes = int(record.get("late_minutes") or 0)
    logs_repo.log_recognitions([{"kind": "SOLO", "session_id": session_id, "prn": best.prn,
                                 "confidence": best.score, "status": status, "latency_ms": latency_ms,
                                 "committed": True}])
    logs_repo.save_snapshot("LATE", encode_jpeg(crop_face(best_img, best_face.bbox, size=200)),
                            session_id=session_id, prn=best.prn)
    if final_status == "LATE":
        notify("LATE", "Marked late", f"You were marked LATE by {late_minutes} min for {_session_label(session)}.",
               recipient_prn=best.prn, data={"session_id": session_id, "late_minutes": late_minutes})
    event("late_marked", {"session_id": session_id, "prn": best.prn, "name": names.get(best.prn),
                          "status": final_status, "late_minutes": late_minutes}, prn=best.prn, staff_only=False)
    reenrolled = maybe_auto_reenroll(best.prn, probe, best.score, quality_ok=True,
                                     liveness_ok=challenge is not None)
    return {
        "prn": best.prn,
        "name": names.get(best.prn),
        "status": final_status,
        "late_minutes": late_minutes,
        "result": proc_result,
        "confidence": round(best.score, 4),
        "match_status": status,
        "liveness": liveness_out,
        "auto_reenrolled": reenrolled,
        "latency_ms": round(latency_ms, 1),
    }


def maybe_auto_reenroll(prn: str, embedding: np.ndarray, confidence: float, *, quality_ok: bool,
                        liveness_ok: bool) -> bool:
    """Confidence drifting down (new haircut, beard, glasses)? Learn a fresh template."""
    s = get_settings()
    if not (s.auto_reenroll and quality_ok and liveness_ok):
        return False
    try:
        recent = logs_repo.recent_confidences(prn, limit=5)
        threshold = face_service.match_threshold()
        if len(recent) < 3 or confidence < threshold:
            return False
        avg = float(np.mean(recent))
        if avg >= threshold + s.reenroll_margin:
            return False
        engine = face_service.get_engine()
        emb_repo.insert_many([emb_repo.build_doc(prn=prn, vector=embedding, model=engine.model_id,
                                                 source="AUTO_REENROLL", quality={"trigger_avg": avg})])
        emb_repo.trim_to_limit(prn, s.max_embeddings_per_student)
        face_service.notify_embeddings_changed()
        notify("REENROLL", "Face profile refreshed",
               "Your recent recognitions had low confidence, so a fresh face template was added automatically.",
               recipient_prn=prn, data={"avg_confidence": avg})
        logger.info("Auto re-enrolled %s (avg confidence %.3f)", prn, avg)
        return True
    except Exception as exc:  # noqa: BLE001 - never fail attendance because of this
        logger.warning("Auto re-enrolment skipped for %s: %s", prn, exc)
        return False


# ------------------------------------------------------------------ QR fallback
def qr_mark(session_id: int, code: str, actor: CurrentUser) -> dict[str, Any]:
    if not actor.prn:
        raise forbidden("Only students can use QR attendance")
    if not verify_qr_code(session_id, code):
        raise AppError(400, "QR_INVALID", "QR code expired or invalid - scan the code currently shown in class")
    with transaction() as conn:
        session = load_session(conn, session_id)
        _, proc_result = att_repo.mark_late(conn, session_id, actor.prn, "QR", None, actor.user_id)
        record = att_repo.get_record(conn, session_id, actor.prn) or {}
    event("qr_marked", {"session_id": session_id, "prn": actor.prn, "status": record.get("status")})
    return {"session_id": session_id, "course_code": session["course_code"], "status": record.get("status"),
            "late_minutes": record.get("late_minutes"), "result": proc_result}


# ------------------------------------------------------------------ live feed
def live_frame(state: ClientState, session_id: int, image_data: str) -> dict[str, Any]:
    s = get_settings()
    now = time.time()
    if state.session_id != session_id or now - state.roster_loaded_at > 60:
        with transaction() as conn:
            session = load_session(conn, session_id)
            assert_can_manage(conn, session, state.user)
            roster = students_repo.course_roster(conn, session["course_id"])
        if state.session_id != session_id:
            state.draft_id, state.seen = None, {}
        state.session_id, state.course_id = session_id, session["course_id"]
        state.roster = {r["prn"]: r["full_name"] for r in roster if r["face_status"] != "PENDING"}
        state.roster_loaded_at = now

    img = decode_image(decode_data_url(image_data), max_side=960)
    started = time.perf_counter()
    faces = face_service.detect(img, max_faces=0)
    threshold = face_service.match_threshold()
    results = match_faces(img, faces, set(state.roster), threshold=threshold, margin=s.low_conf_margin,
                          min_face_px=s.group_min_face_px, check_spoof=True, with_crops=False)
    latency_ms = (time.perf_counter() - started) * 1000

    seen_now = {r.prn: float(r.confidence) for r in results if r.prn and r.status in RECOGNISED}
    new_prns = [p for p in seen_now if p not in state.seen]
    for prn, conf in seen_now.items():
        state.seen[prn] = max(conf, state.seen.get(prn, 0.0))
    if seen_now:
        try:
            state.draft_id = logs_repo.upsert_live_seen(state.draft_id, session_id, state.user.user_id, seen_now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("live draft update failed: %s", exc)
    if new_prns:
        logs_repo.log_recognitions([{"kind": "LIVE", "session_id": session_id, "prn": p, "confidence": seen_now[p],
                                     "status": "MATCHED" if seen_now[p] >= threshold + s.low_conf_margin
                                     else "LOW_CONFIDENCE", "latency_ms": latency_ms,
                                     "draft_id": state.draft_id} for p in new_prns])
        event("live_seen", {"session_id": session_id,
                            "students": [{"prn": p, "name": state.roster.get(p)} for p in new_prns]})
    return {
        "type": "recognition",
        "session_id": session_id,
        "latency_ms": round(latency_ms, 1),
        "frame": {"width": int(img.shape[1]), "height": int(img.shape[0])},
        "faces": [r.public(state.roster, include_crop=False) for r in results],
        "draft_id": state.draft_id,
        "seen": [{"prn": p, "name": state.roster.get(p), "confidence": round(c, 4)}
                 for p, c in sorted(state.seen.items(), key=lambda kv: -kv[1])],
    }


def session_roster(session_id: int, actor: CurrentUser) -> dict[str, Any]:
    with transaction() as conn:
        session = load_session(conn, session_id)
        if not actor.is_staff:
            raise forbidden()
        roster = sessions_repo.roster_with_status(conn, session_id)
    return {"session": session, "students": roster, "today": local_today().isoformat()}
