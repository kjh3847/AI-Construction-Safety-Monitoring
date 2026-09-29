import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone

# 실행 위치가 달라도 항상 backend에 저장
DB_PATH = Path(__file__).resolve().parent / "safety.db"


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS safety_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                model_name TEXT,
                confidence REAL,
                snapshot_path TEXT,
                review_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                )
            )
        """)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(safety_events)')}
        for name, kind in [('event_key', 'TEXT'), ('source_name', 'TEXT'), ('video_seconds', 'REAL'),
                           ('recording_id', 'TEXT'), ('frame_id', 'INTEGER'),
                           ('detected_at', 'TEXT'), ('person_count', 'INTEGER'),
                           ('noncompliant_person_count', 'INTEGER'), ('event_person_count', 'INTEGER'),
                           ('unassigned_negative_count', 'INTEGER'), ('association_method', 'TEXT'),
                           ('person_track_id', 'TEXT'), ('violation_types', 'TEXT'),
                           ('event_reason', 'TEXT'), ('sustained_seconds', 'REAL'), ('repeat_index', 'INTEGER')]:
            if name not in columns:
                conn.execute(f'ALTER TABLE safety_events ADD COLUMN {name} {kind}')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_safety_event_key ON safety_events(event_key)')
        conn.execute('CREATE TABLE IF NOT EXISTS monitor_settings (key TEXT PRIMARY KEY, value INTEGER NOT NULL)')


def save_event(
    camera_name,
    event_type,
    model_name=None,
    confidence=None,
    snapshot_path=None,
    event_key=None,
    source_name=None,
    video_seconds=None,
    detected_at=None,
    counts=None,
    person_track_id=None,
    violation_types=None,
    event_reason=None,
    sustained_seconds=None,
    repeat_index=None,
):
    counts = counts or {}
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO safety_events (
                camera_name, event_type, model_name,
                confidence, snapshot_path, event_key, source_name, video_seconds,
                detected_at, person_count, noncompliant_person_count, event_person_count,
                unassigned_negative_count, association_method, person_track_id, violation_types,
                event_reason, sustained_seconds, repeat_index
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_key) DO NOTHING
        """, (
            camera_name, event_type, model_name,
            confidence, snapshot_path, event_key, source_name, video_seconds,
            detected_at, counts.get('person_count'), counts.get('noncompliant_person_count'),
            counts.get('event_person_count'), counts.get('unassigned_negative_count'), counts.get('association_method'),
            person_track_id, json.dumps(violation_types) if violation_types else None,
            event_reason, sustained_seconds, repeat_index
        ))
        return cursor.lastrowid if cursor.rowcount else None


def fill_event_counts(event_key, counts):
    # Only add missing evidence. Replaying a test must not replace original
    # timestamps, review status, confidence, or previously recorded counts.
    if counts.get('event_person_count') is None:
        return
    with get_connection() as conn:
        conn.execute('''UPDATE safety_events SET person_count=?, noncompliant_person_count=?,
            event_person_count=?, unassigned_negative_count=?, association_method=?
            WHERE event_key=? AND event_person_count IS NULL''',
            (counts['person_count'], counts['noncompliant_person_count'], counts['event_person_count'],
             counts['unassigned_negative_count'], counts['association_method'], event_key))


def get_events(limit=100, offset=0, day=None, event_type=None, review_status=None, camera_name=None):
    clauses, params = [], []
    if day:
        start = datetime.combine(day, time(), timezone(timedelta(hours=9)))
        clauses.append('created_at >= ? AND created_at < ?')
        params.extend([(start.astimezone(timezone.utc)).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                       ((start + timedelta(days=1)).astimezone(timezone.utc)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')])
    if event_type:
        clauses.append('(event_type = ? OR EXISTS (SELECT 1 FROM json_each(COALESCE(violation_types, \'[]\')) WHERE value = ?))')
        params.extend([event_type, event_type])
    if review_status:
        clauses.append('review_status = ?')
        params.append(review_status)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    if camera_name:
        clauses.append('camera_name = ?')
        params.append(camera_name)
        where = ' WHERE ' + ' AND '.join(clauses)
    with get_connection() as conn:
        rows = conn.execute(f"""
            SELECT *
            FROM safety_events
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (*params, limit, offset)).fetchall()

        return [dict(row) for row in rows]


def event_summary():
    with get_connection() as conn:
        return dict(conn.execute("""
            SELECT COUNT(*) AS total,
                COALESCE(SUM(review_status = 'pending'), 0) AS pending
            FROM safety_events
        """).fetchone())


def today_event_count():
    today = datetime.now(timezone(timedelta(hours=9))).date()
    start = datetime.combine(today, time(), timezone(timedelta(hours=9))).astimezone(timezone.utc)
    with get_connection() as conn:
        return conn.execute("""SELECT COUNT(*) FROM safety_events
            WHERE event_type IN ('NO-Hardhat', 'NO-Safety Vest')
            AND created_at >= ? AND created_at < ?""",
            (start.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
             (start + timedelta(days=1)).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))).fetchone()[0]


def get_event(event_id):
    with get_connection() as conn:
        row = conn.execute('SELECT * FROM safety_events WHERE id = ?', (event_id,)).fetchone()
        return dict(row) if row else None


def attach_recording(event_key, recording_id, frame_id, snapshot_path):
    # Replayed test input may match an older event. Attach real evidence without
    # changing its original timestamp, review state, confidence or identity.
    with get_connection() as conn:
        conn.execute('''UPDATE safety_events SET recording_id=?, frame_id=?,
            snapshot_path=COALESCE(snapshot_path, ?) WHERE event_key=?''',
            (recording_id, frame_id, snapshot_path, event_key))


def retention_seconds(value=None):
    with get_connection() as conn:
        if value is not None:
            conn.execute("INSERT INTO monitor_settings VALUES ('retention_seconds', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
        row = conn.execute("SELECT value FROM monitor_settings WHERE key='retention_seconds'").fetchone()
        return row[0] if row else 300


def review_event(event_id):
    with get_connection() as conn:
        conn.execute("UPDATE safety_events SET review_status = 'reviewed' WHERE id = ?", (event_id,))
        row = conn.execute('SELECT * FROM safety_events WHERE id = ?', (event_id,)).fetchone()
        return dict(row) if row else None


if __name__ == "__main__":
    init_db()
    print(f"DB 준비 완료: {DB_PATH}")
