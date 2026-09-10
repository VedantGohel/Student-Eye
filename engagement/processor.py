"""
processor.py — StudentEye Final Processor

Fixes:
  1. Spatial face tracking — persistent IDs across frames via IoU matching
  2. Eyes-closed penalty — EAR below threshold directly reduces attention score
  3. Embedding-based recognition — pre-extract embeddings from profile photos,
     compare via cosine distance (fast + reliable, no full-image verify)

Pipeline per sampled frame:
  1. Downsample → detect faces (Haar + NMS)
  2. Match detected faces to tracked faces via IoU
  3. DeepFace emotion on each face crop
  4. Bbox-based pose → yaw / pitch
  5. EAR estimation + closed-eye penalty
  6. Weighted attention score
  7. Face recognition via embedding comparison
  8. Save live JPEG frame + DB updates
"""

import cv2
import numpy as np
import logging
import math
import threading
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EMOTION_SCORES = {
    'neutral':  70,
    'happy':    80,
    'surprise': 65,
    'sad':      30,
    'angry':    20,
    'fear':     25,
    'disgust':  15,
}

EAR_CLOSED_THRESHOLD  = 0.22
EAR_CLOSED_PENALTY    = 0.45   # multiply attention by this when eyes closed
MIN_FACE_PX           = 60
DETECT_WIDTH          = 1280
IOU_MATCH_THRESHOLD   = 0.22   # min IoU to consider same face across frames
MAX_FRAMES_MISSING    = 12     # frames a face can be absent before ID retired
RECOGNITION_THRESHOLD = 0.45   # cosine distance threshold for face match


# ---------------------------------------------------------------------------
# Cascade singletons
# ---------------------------------------------------------------------------
_face_cascade = None
_eye_cascade  = None

def _get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        # alt2 detects more faces including bearded/glasses faces
        _face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml'
        )
    return _face_cascade

def _get_eye_cascade():
    global _eye_cascade
    if _eye_cascade is None:
        _eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_eye.xml'
        )
    return _eye_cascade


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def process_video_async(session):
    from engagement.models import EngagementSession
    session.status = EngagementSession.PROCESSING
    session.save(update_fields=['status'])
    thread = threading.Thread(
        target=_run_with_error_handling,
        args=(session.id,),
        daemon=True,
    )
    thread.start()
    logger.info("Session %d: thread started", session.id)


def _run_with_error_handling(session_id):
    import traceback
    from django.db import connection
    connection.close()
    from engagement.models import EngagementSession
    session = EngagementSession.objects.get(id=session_id)
    try:
        _run_analysis(session)
        session.refresh_from_db()
        session.status = EngagementSession.DONE
        session.save(update_fields=[
            'status', 'avg_attention', 'total_students',
            'frames_processed', 'processing_time_sec', 'annotated_video',
        ])
        logger.info("Session %d DONE. Avg: %.1f%%", session_id, session.avg_attention or 0)
    except Exception as exc:
        try:
            session.refresh_from_db()
            session.status        = EngagementSession.FAILED
            session.error_message = traceback.format_exc()
            session.save(update_fields=['status', 'error_message'])
        except Exception:
            pass
        logger.error("Session %d FAILED: %s", session_id, exc, exc_info=True)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _run_analysis(session):
    import time
    from deepface import DeepFace
    from engagement.models import StudentAttentionScore, FrameEmotionLog
    from django.conf import settings

    t_start = time.perf_counter()

    cap = cv2.VideoCapture(session.video.path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {session.video.path}")

    fps          = cap.get(cv2.CAP_PROP_FPS) or 30
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps if fps > 0 else 0

    sample_every = max(1, int(fps * 2))
    if duration_sec > 0 and total_frames // sample_every < 20:
        sample_every = max(1, total_frames // 20)

    scale_x = width  / DETECT_WIDTH
    scale_y = height / max(1, int(height * DETECT_WIDTH / width))

    annotated_path  = _get_annotated_path(session)
    live_frames_dir = _get_live_frames_dir(session)

    out_fps = max(1, min(fps / sample_every, 5))
    writer  = cv2.VideoWriter(
        str(annotated_path),
        cv2.VideoWriter_fourcc(*'mp4v'),
        out_fps, (width, height),
    )

    # Pre-build recognition DB with embeddings
    student_db = _build_embedding_db(session, DeepFace)
    logger.info("Session %d: %d students in embedding DB", session.id, len(student_db))

    # face_store: track_id → accumulator dict
    face_store    = {}
    # tracker: track_id → {bbox, frames_missing}
    tracker       = {}
    next_track_id = 0
    attendance_set = set()

    frames_processed = 0
    frame_idx        = 0
    face_cascade     = _get_face_cascade()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_every != 0:
            frame_idx += 1
            continue

        timestamp_sec = frame_idx / fps
        annotated     = frame.copy()

        # Detect faces on downsampled frame
        detect_h  = int(height * DETECT_WIDTH / width)
        small     = cv2.resize(frame, (DETECT_WIDTH, detect_h))

        # ROI: ignore top 20% of frame (windows/ceiling cause false positives)
        roi_y     = int(detect_h * 0.20)
        gray_full = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        gray_roi  = gray_full[roi_y:, :]

        raw_in_roi = face_cascade.detectMultiScale(
            gray_roi,
            scaleFactor=1.05,
            minNeighbors=5,
            minSize=(MIN_FACE_PX, MIN_FACE_PX),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )

        # Shift ROI detections back to full image coords
        raw_faces = []
        if len(raw_in_roi) > 0:
            for (fx, fy, fw, fh) in raw_in_roi:
                raw_faces.append((fx, fy + roi_y, fw, fh))

        # Scale to full resolution
        faces_full = []
        if len(raw_faces) > 0:
            raw_list = _nms_faces(sorted(raw_faces, key=lambda f: f[0]))
            for (fx, fy, fw, fh) in raw_list:
                faces_full.append((
                    int(fx * scale_x), int(fy * scale_y),
                    int(fw * scale_x), int(fh * scale_y),
                ))

        # Match detected faces to existing tracks via IoU
        matched_tracks, unmatched_dets, unmatched_tracks = _match_faces(
            faces_full, tracker
        )

        # Increment missing counter for unmatched tracks
        for tid in unmatched_tracks:
            tracker[tid]['frames_missing'] += 1

        # Retire tracks missing too long
        retired = [tid for tid, t in tracker.items()
                   if t['frames_missing'] > MAX_FRAMES_MISSING]
        for tid in retired:
            del tracker[tid]

        # Create new tracks for unmatched detections
        for det_idx in unmatched_dets:
            tracker[next_track_id] = {
                'bbox': faces_full[det_idx],
                'frames_missing': 0,
            }
            next_track_id += 1

        # Update bbox for matched tracks
        for tid, det_idx in matched_tracks.items():
            tracker[tid]['bbox']           = faces_full[det_idx]
            tracker[tid]['frames_missing'] = 0

        # Process each matched/new detection
        frame_scores  = []
        frame_yaws    = []
        frame_pitches = []
        frame_ears    = []

        # Build map: det_idx → track_id
        det_to_track = {det_idx: tid for tid, det_idx in matched_tracks.items()}
        for det_idx in unmatched_dets:
            # Find newly created track
            for tid, t in tracker.items():
                if t['bbox'] == faces_full[det_idx] and t['frames_missing'] == 0:
                    det_to_track[det_idx] = tid
                    break

        for det_idx, (fx, fy, fw, fh) in enumerate(faces_full):
            track_id = det_to_track.get(det_idx)
            if track_id is None:
                continue

            x1 = max(0, fx);  y1 = max(0, fy)
            x2 = min(width, fx+fw); y2 = min(height, fy+fh)
            face_crop = frame[y1:y2, x1:x2]
            if face_crop.size == 0:
                continue

            # Emotion
            dominant, emotion_s = _get_emotion(face_crop, DeepFace)

            # Pose
            yaw, pitch  = _estimate_pose(fx, fy, fw, fh, width, height)
            yaw_score   = max(0.0, 100.0 - abs(yaw)   * 1.8)
            pitch_score = max(0.0, 100.0 - abs(pitch) * 1.8)
            pose_s      = round(yaw_score * 0.6 + pitch_score * 0.4, 1)

            # EAR — with closed-eye penalty
            ear   = _estimate_ear(face_crop)
            ear_s = round(min(100.0, ear * 230.0), 1)

            # Base attention score
            attention = (
                emotion_s * 0.25 +
                pose_s    * 0.35 +
                ear_s     * 0.20 +
                yaw_score * 0.20
            )

            # Apply closed-eye penalty
            eyes_closed = ear < EAR_CLOSED_THRESHOLD
            if eyes_closed:
                attention *= EAR_CLOSED_PENALTY

            attention = round(float(np.clip(attention, 0, 100)), 1)

            # Initialise store for new track
            if track_id not in face_store:
                # Try face recognition on first appearance
                student_id, student_name, roll_no = _recognize_face_embedding(
                    face_crop, student_db, DeepFace
                )
                display_name = student_name if student_name else f"Unknown-{track_id + 1}"
                face_store[track_id] = {
                    'student_id':   student_id,
                    'student_name': display_name,
                    'roll_no':      roll_no or f"U{track_id + 1}",
                    'attention': [], 'emotions': {},
                    'yaws': [], 'pitches': [], 'ears': [],
                    'pose_scores': [], 'ear_scores': [], 'emotion_scores': [],
                    'eyes_closed_frames': 0,
                }
            else:
                # Re-try recognition every 3 frames if still unknown
                fd = face_store[track_id]
                if not fd['student_id'] and len(fd['attention']) % 3 == 0:
                    sid, sname, sroll = _recognize_face_embedding(
                        face_crop, student_db, DeepFace
                    )
                    if sid:
                        fd['student_id']   = sid
                        fd['student_name'] = sname
                        fd['roll_no']      = sroll
                        logger.info("Late recognition: track %d -> %s", track_id, sname)

            fd = face_store[track_id]
            fd['attention'].append(attention)
            fd['emotions'][dominant] = fd['emotions'].get(dominant, 0) + 1
            fd['yaws'].append(yaw);    fd['pitches'].append(pitch)
            fd['ears'].append(ear)
            fd['pose_scores'].append(pose_s)
            fd['ear_scores'].append(ear_s)
            fd['emotion_scores'].append(float(emotion_s))
            if eyes_closed:
                fd['eyes_closed_frames'] += 1

            frame_scores.append(attention)
            frame_yaws.append(yaw);    frame_pitches.append(pitch)
            frame_ears.append(ear)

            # Annotation
            color      = _score_color(attention)
            name_label = fd['student_name']
            eye_str    = " [EYES CLOSED]" if eyes_closed else ""
            label      = f"{name_label} | {attention:.0f}%{eye_str}"
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 3)
            _draw_label(annotated, label, x1, y1, color)
            _draw_pose_arrows(annotated, x1, y1, fw, fh, yaw, pitch)
            cv2.putText(annotated, f"EAR:{ear:.2f} Yaw:{yaw:.0f}° {dominant[:3].upper()}",
                        (x1, y2+28), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 2, cv2.LINE_AA)
            cv2.putText(annotated, f"ID:{track_id}",
                        (x1, y2+50), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200,200,200), 1, cv2.LINE_AA)

            # Attendance
            if fd['student_id'] and fd['student_id'] not in attendance_set:
                _mark_attendance(session, fd['student_id'])
                attendance_set.add(fd['student_id'])

        avg_frame = round(sum(frame_scores)/len(frame_scores), 1) if frame_scores else None
        _draw_hud(annotated, frame_idx, timestamp_sec, len(frame_scores), avg_frame,
                  total_tracks=len(face_store))
        writer.write(annotated)
        _save_live_frame(annotated, live_frames_dir, frames_processed)

        FrameEmotionLog.objects.create(
            session=session,
            frame_index=frame_idx,
            timestamp_sec=round(timestamp_sec, 2),
            face_count=len(frame_scores),
            avg_attention=avg_frame,
            avg_yaw=round(sum(frame_yaws)/len(frame_yaws), 2)        if frame_yaws    else None,
            avg_pitch=round(sum(frame_pitches)/len(frame_pitches), 2) if frame_pitches else None,
            avg_ear=round(sum(frame_ears)/len(frame_ears), 4)         if frame_ears    else None,
        )

        session.frames_processed = frames_processed
        session.save(update_fields=['frames_processed'])

        if face_store:
            _upsert_live_scores(session, face_store)

        frames_processed += 1
        frame_idx += 1

    cap.release()
    writer.release()

    # Filter out ghost tracks — keep faces seen in at least 10% of frames
    # (min 2, max 5) so short and long videos are both handled correctly
    MIN_FRAMES = max(2, min(5, frames_processed // 10))
    face_store = {k: v for k, v in face_store.items() if len(v["attention"]) >= MIN_FRAMES}
    logger.info("Session %d: %d tracks after min-frame filter (min=%d)", session.id, len(face_store), MIN_FRAMES)

    # Merge duplicate student tracks — same student_id should be one record
    face_store = _merge_duplicate_tracks(face_store)
    logger.info("Session %d: %d tracks after dedup", session.id, len(face_store))

    # CRITICAL: Delete ALL existing score records (from live upserts during processing)
    # and re-insert clean final merged records so stale Unknown-N entries are gone
    from engagement.models import StudentAttentionScore
    StudentAttentionScore.objects.filter(session=session).delete()
    all_avg = _upsert_live_scores(session, face_store, final=True)

    from django.conf import settings as dj_settings
    rel = str(annotated_path).replace(str(dj_settings.MEDIA_ROOT), '').lstrip('/\\').replace('\\', '/')
    session.annotated_video     = rel
    session.avg_attention       = round(sum(all_avg)/len(all_avg), 1) if all_avg else 0.0
    session.total_students      = len(all_avg)
    session.frames_processed    = frames_processed
    session.processing_time_sec = round(time.perf_counter() - t_start, 2)
    session.save(update_fields=[
        'annotated_video', 'avg_attention', 'total_students',
        'frames_processed', 'processing_time_sec'
    ])


# ---------------------------------------------------------------------------
# Merge duplicate tracks (same student recognised across multiple IDs)
# ---------------------------------------------------------------------------

def _merge_duplicate_tracks(face_store):
    """
    Merge tracks that belong to the same physical person:
    1. Known students: merge by student_id
    2. Unknown tracks: merge by horizontal position (same X zone = same person)
    """
    if not face_store:
        return face_store

    def _merge_into(target, source):
        target['attention'].extend(source['attention'])
        target['yaws'].extend(source['yaws'])
        target['pitches'].extend(source['pitches'])
        target['ears'].extend(source['ears'])
        target['pose_scores'].extend(source['pose_scores'])
        target['ear_scores'].extend(source['ear_scores'])
        target['emotion_scores'].extend(source['emotion_scores'])
        target['eyes_closed_frames'] += source['eyes_closed_frames']
        for emotion, count in source['emotions'].items():
            target['emotions'][emotion] = target['emotions'].get(emotion, 0) + count
        # If source has recognition, upgrade target
        if source['student_id'] and not target['student_id']:
            target['student_id']   = source['student_id']
            target['student_name'] = source['student_name']
            target['roll_no']      = source['roll_no']

    # Step 1: Merge known students with same student_id
    merged = {}
    id_to_key = {}

    for key, fd in face_store.items():
        sid = fd['student_id']
        if sid and sid in id_to_key:
            _merge_into(merged[id_to_key[sid]], fd)
        else:
            merged[key] = {k: list(v) if isinstance(v, list) else v
                           for k, v in fd.items()}
            merged[key]['emotions'] = dict(fd['emotions'])
            if sid:
                id_to_key[sid] = key

    # Step 2: Merge Unknown tracks by horizontal position
    # Tracks whose avg yaw falls within 15 degrees of each other are same person
    unknown_keys = [k for k, v in merged.items() if not v['student_id']]

    def avg_yaw(fd):
        return sum(fd['yaws']) / len(fd['yaws']) if fd['yaws'] else 0

    # Sort unknowns by avg yaw (horizontal position)
    unknown_keys.sort(key=lambda k: avg_yaw(merged[k]))

    # Merge unknowns within 15 degrees of each other
    YAW_MERGE_THRESHOLD = 15.0
    to_delete = set()
    for i, k1 in enumerate(unknown_keys):
        if k1 in to_delete:
            continue
        for k2 in unknown_keys[i+1:]:
            if k2 in to_delete:
                continue
            y1 = avg_yaw(merged[k1])
            y2 = avg_yaw(merged[k2])
            if abs(y1 - y2) <= YAW_MERGE_THRESHOLD:
                _merge_into(merged[k1], merged[k2])
                to_delete.add(k2)

    for k in to_delete:
        del merged[k]

    # Step 3: Renumber Unknown tracks cleanly (Unknown-1, Unknown-2...)
    unknown_count = 0
    for key, fd in merged.items():
        if not fd['student_id']:
            unknown_count += 1
            fd['student_name'] = f"Unknown-{unknown_count}"
            fd['roll_no']      = f"U{unknown_count}"

    return merged


# ---------------------------------------------------------------------------
# Spatial face tracking via IoU
# ---------------------------------------------------------------------------

def _iou(b1, b2):
    """Compute IoU between two bboxes (x,y,w,h)."""
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    xa = max(x1, x2);  ya = max(y1, y2)
    xb = min(x1+w1, x2+w2); yb = min(y1+h1, y2+h2)
    inter = max(0, xb-xa) * max(0, yb-ya)
    union = w1*h1 + w2*h2 - inter
    return inter / union if union > 0 else 0.0


def _match_faces(detections, tracker):
    """
    Match current frame detections to existing tracks via IoU.
    Returns:
      matched_tracks: {track_id: det_idx}
      unmatched_dets: [det_idx]  — new faces
      unmatched_tracks: [track_id]  — faces that disappeared
    """
    if not tracker or not detections:
        return {}, list(range(len(detections))), list(tracker.keys())

    track_ids  = list(tracker.keys())
    matched    = {}
    used_dets  = set()
    used_tracks= set()

    # Build IoU matrix
    for tid in track_ids:
        best_iou  = IOU_MATCH_THRESHOLD
        best_det  = None
        for di, det in enumerate(detections):
            if di in used_dets:
                continue
            iou = _iou(tracker[tid]['bbox'], det)
            if iou > best_iou:
                best_iou = iou
                best_det = di
        if best_det is not None:
            matched[tid] = best_det
            used_dets.add(best_det)
            used_tracks.add(tid)

    unmatched_dets    = [i for i in range(len(detections)) if i not in used_dets]
    unmatched_tracks  = [tid for tid in track_ids if tid not in used_tracks]
    return matched, unmatched_dets, unmatched_tracks


# ---------------------------------------------------------------------------
# Embedding-based face recognition
# ---------------------------------------------------------------------------

def _build_embedding_db(session, DeepFace):
    """
    Pre-extract face embeddings from all registered student photos.
    Returns list of {student_id, student_name, roll_no, embedding}.
    """
    from core.models import Student
    from django.conf import settings

    db = []
    students = Student.objects.select_related('user').filter(
        user__profile_pic__isnull=False
    ).exclude(user__profile_pic='')

    if session.subject and session.subject.course:
        students = students.filter(course=session.subject.course)

    for student in students:
        try:
            pic_path = os.path.join(settings.MEDIA_ROOT, str(student.user.profile_pic))
            if not os.path.exists(pic_path):
                continue

            img = cv2.imread(pic_path)
            if img is None:
                continue

            # Extract embedding from profile photo
            result = DeepFace.represent(
                img,
                model_name='Facenet',
                enforce_detection=False,
                detector_backend='opencv',
            )
            if isinstance(result, list):
                result = result[0]
            embedding = np.array(result['embedding'], dtype=np.float32)

            db.append({
                'student_id':   student.id,
                'student_name': student.user.get_full_name() or student.user.username,
                'roll_no':      student.roll_no or str(student.id),
                'embedding':    embedding,
            })
            logger.info("Embedding extracted for %s", student.user.get_full_name())
        except Exception as e:
            logger.warning("Failed embedding for student %d: %s", student.id, e)
            continue

    return db


def _recognize_face_embedding(face_crop, student_db, DeepFace):
    """
    Compare face_crop embedding against student DB.
    Returns (student_id, student_name, roll_no) or (None, None, None).
    """
    if not student_db:
        return None, None, None

    try:
        h, w = face_crop.shape[:2]
        if w < 48 or h < 48:
            scale = max(48/w, 48/h)
            face_crop = cv2.resize(face_crop, (int(w*scale), int(h*scale)))

        result = DeepFace.represent(
            face_crop,
            model_name='Facenet',
            enforce_detection=False,
            detector_backend='skip',
        )
        if isinstance(result, list):
            result = result[0]

        query_emb = np.array(result['embedding'], dtype=np.float32)

        best_match = None
        best_dist  = float('inf')

        for entry in student_db:
            # Cosine distance
            dot  = np.dot(query_emb, entry['embedding'])
            norm = np.linalg.norm(query_emb) * np.linalg.norm(entry['embedding'])
            dist = 1.0 - (dot / norm) if norm > 0 else 1.0
            if dist < best_dist:
                best_dist  = dist
                best_match = entry

        if best_match and best_dist < RECOGNITION_THRESHOLD:
            logger.debug("Recognised %s (dist=%.3f)", best_match['student_name'], best_dist)
            return best_match['student_id'], best_match['student_name'], best_match['roll_no']

    except Exception as e:
        logger.debug("Recognition failed: %s", e)

    return None, None, None


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

def _mark_attendance(session, student_id):
    from core.models import Attendance, AttendanceReport, Student
    if not session.subject:
        return
    try:
        student = Student.objects.get(id=student_id)
        attendance, _ = Attendance.objects.get_or_create(
            subject=session.subject,
            date=session.session_date,
        )
        AttendanceReport.objects.update_or_create(
            attendance=attendance,
            student=student,
            defaults={'status': True},
        )
        logger.info("Attendance marked: %s", student.user.get_full_name())
    except Exception as e:
        logger.warning("Attendance failed for student %d: %s", student_id, e)


# ---------------------------------------------------------------------------
# Live upsert
# ---------------------------------------------------------------------------

def _upsert_live_scores(session, face_store, final=False):
    from engagement.models import StudentAttentionScore
    from core.models import Student

    def _avg(lst): return round(sum(lst)/len(lst), 2) if lst else 0.0

    all_avg = []
    for track_id, fd in face_store.items():
        if not fd['attention']:
            continue

        avg_att    = round(_avg(fd['attention']), 1)
        dominant   = max(fd['emotions'], key=fd['emotions'].get)
        total_f    = len(fd['ears'])
        closed_pct = round(fd['eyes_closed_frames'] / total_f * 100, 1) if total_f else 0.0

        student_obj = None
        if fd['student_id']:
            try:
                student_obj = Student.objects.get(id=fd['student_id'])
            except Exception:
                pass

        StudentAttentionScore.objects.update_or_create(
            session=session,
            roll_no=fd['roll_no'],
            defaults=dict(
                student=student_obj,
                student_name=fd['student_name'],
                avg_attention=avg_att,
                min_attention=round(min(fd['attention']), 1),
                max_attention=round(max(fd['attention']), 1),
                frames_counted=len(fd['attention']),
                dominant_emotion=dominant,
                avg_yaw=_avg(fd['yaws']),
                avg_pitch=_avg(fd['pitches']),
                avg_roll=0.0,
                avg_ear=_avg(fd['ears']),
                eyes_closed_pct=closed_pct,
                pose_score=_avg(fd['pose_scores']),
                ear_score=_avg(fd['ear_scores']),
                emotion_score=_avg(fd['emotion_scores']),
            )
        )
        all_avg.append(avg_att)

    if all_avg:
        session.avg_attention  = round(sum(all_avg)/len(all_avg), 1)
        session.total_students = len(all_avg)
        session.save(update_fields=['avg_attention', 'total_students'])

    return all_avg


def _upsert_live_scores_interim(session, face_store):
    """Wrapper for live (interim) updates — updates avg_attention only, not total_students."""
    result = _upsert_live_scores(session, face_store)
    return result


# ---------------------------------------------------------------------------
# Emotion
# ---------------------------------------------------------------------------

def _get_emotion(face_crop, DeepFace):
    try:
        h, w = face_crop.shape[:2]
        if w < 48 or h < 48:
            scale = max(48/w, 48/h)
            face_crop = cv2.resize(face_crop, (int(w*scale), int(h*scale)))
        result = DeepFace.analyze(
            face_crop, actions=['emotion'],
            enforce_detection=False,
            detector_backend='skip',
            silent=True,
        )
        if isinstance(result, list):
            result = result[0]
        dominant = result.get('dominant_emotion', 'neutral')
        conf     = result.get('emotion', {}).get(dominant, 50) / 100.0
        base     = EMOTION_SCORES.get(dominant, 50)
        return dominant, int(base * (0.5 + 0.5 * conf))
    except Exception:
        return 'neutral', 60


# ---------------------------------------------------------------------------
# Pose + EAR
# ---------------------------------------------------------------------------

def _estimate_pose(fx, fy, fw, fh, frame_w, frame_h):
    norm_x = (fx + fw/2 - frame_w/2) / (frame_w/2)
    yaw    = round(float(np.clip(norm_x * 45.0, -45.0, 45.0)), 2)
    norm_y = (fy + fh/2 - frame_h*0.30) / (frame_h * 0.4)
    pitch  = round(float(np.clip(norm_y * 30.0, -30.0, 30.0)), 2)
    return yaw, pitch


def _estimate_ear(face_crop):
    try:
        h, w   = face_crop.shape[:2]
        region = face_crop[:int(h*0.55), :]
        if region.size == 0:
            return 0.28
        gray    = cv2.equalizeHist(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY))
        cascade = _get_eye_cascade()
        eyes    = cascade.detectMultiScale(gray, 1.1, 4, minSize=(12, 12))
        if len(eyes) >= 2:
            ears = [min(0.45, max(0.10, eh/max(ew,1)*0.55)) for (_,_,ew,eh) in eyes[:2]]
            return round(sum(ears)/2, 4)
        elif len(eyes) == 1:
            (_,_,ew,eh) = eyes[0]
            return round(min(0.45, max(0.10, eh/max(ew,1)*0.55)), 4)
        brightness = np.mean(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)) / 255.0
        return round(float(np.clip(0.15 + brightness*0.30, 0.15, 0.45)), 4)
    except Exception:
        return 0.28


# ---------------------------------------------------------------------------
# NMS
# ---------------------------------------------------------------------------

def _nms_faces(faces, overlap_thresh=0.35):
    if len(faces) == 0:
        return faces
    boxes = np.array([[x,y,x+w,y+h] for (x,y,w,h) in faces], dtype=np.float32)
    x1,y1,x2,y2 = boxes[:,0],boxes[:,1],boxes[:,2],boxes[:,3]
    areas = (x2-x1)*(y2-y1)
    order = areas.argsort()[::-1]
    keep  = []
    while order.size > 0:
        i = order[0]; keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        iou = (np.maximum(0,xx2-xx1)*np.maximum(0,yy2-yy1)) / \
              (areas[i]+areas[order[1:]]-np.maximum(0,xx2-xx1)*np.maximum(0,yy2-yy1)+1e-6)
        order = order[np.where(iou<=overlap_thresh)[0]+1]
    return [faces[k] for k in keep]


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _score_color(score):
    if score >= 70: return (50, 200, 80)
    if score >= 40: return (30, 160, 240)
    return (50, 60, 220)

def _draw_label(frame, text, x, y, color):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 2)
    by = max(y-6, th+6)
    cv2.rectangle(frame, (x, by-th-6), (x+tw+10, by+2), color, -1)
    cv2.putText(frame, text, (x+5, by),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255,255,255), 2, cv2.LINE_AA)

def _draw_pose_arrows(frame, x, y, w, h, yaw, pitch):
    cx, cy = x+w//2, y+h//2
    alen   = max(w//3, 20)
    cv2.arrowedLine(frame, (cx,cy),
                    (int(cx+alen*math.sin(math.radians(yaw))), cy),
                    (220,80,30), 2, tipLength=0.35)
    cv2.arrowedLine(frame, (cx,cy),
                    (cx, int(cy-alen*math.sin(math.radians(pitch)))),
                    (50,200,50), 2, tipLength=0.35)

def _draw_hud(frame, frame_idx, timestamp, face_count, avg_attn, total_tracks=0):
    lines = [
        f"Frame:{frame_idx:05d}  T:{timestamp:.1f}s",
        f"Faces this frame: {face_count}",
        f"Total tracked: {total_tracks}",
        f"Avg Attn: {avg_attn:.1f}%" if avg_attn else "Avg Attn: --",
        "StudentEye AI",
    ]
    for i, line in enumerate(lines):
        yp = 30+i*24
        cv2.putText(frame, line, (12,yp), cv2.FONT_HERSHEY_SIMPLEX,
                    0.60, (0,0,0), 4, cv2.LINE_AA)
        cv2.putText(frame, line, (12,yp), cv2.FONT_HERSHEY_SIMPLEX,
                    0.60, (230,240,255), 2, cv2.LINE_AA)

def _save_live_frame(frame, live_dir, frame_num):
    try:
        h, w = frame.shape[:2]
        if w > 1280:
            frame = cv2.resize(frame, (1280, int(h*1280/w)))
        path = live_dir / f"frame_{frame_num:04d}.jpg"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        for old in sorted(live_dir.glob("frame_*.jpg"))[:-5]:
            try: old.unlink()
            except: pass
    except Exception as e:
        logger.warning("Live frame save failed: %s", e)

def _get_annotated_path(session):
    from django.conf import settings
    d = Path(settings.MEDIA_ROOT) / 'annotated'
    d.mkdir(parents=True, exist_ok=True)
    return d / f"session_{session.id}_annotated.mp4"

def _get_live_frames_dir(session):
    from django.conf import settings
    d = Path(settings.MEDIA_ROOT) / 'live_frames' / f"session_{session.id}"
    d.mkdir(parents=True, exist_ok=True)
    return d
