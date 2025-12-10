"""
SQLite database module for the webcam pipeline demo.

Stores detection events, pipeline stage state, and aggregated counts.
Designed to be lightweight and work well on Raspberry Pi 5.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent / "pipeline.db"


@contextmanager
def get_db(db_path: Path = DEFAULT_DB_PATH):
    """Context manager for database access - creates fresh connection each time."""
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Use DELETE mode instead of WAL to avoid -shm/-wal files
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Initialize the database schema."""
    with get_db(db_path) as conn:
        conn.executescript("""
            -- Detection events table
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                category TEXT NOT NULL,
                filename TEXT NOT NULL,
                confidence REAL,
                processing_time_ms REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Index for fast queries
            CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_detections_category ON detections(category);

            -- Pipeline stage state
            CREATE TABLE IF NOT EXISTS pipeline_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Aggregated counts (updated on each detection)
            CREATE TABLE IF NOT EXISTS counts (
                category TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_detected_at REAL
            );

            -- Initialize count rows
            INSERT OR IGNORE INTO counts (category, count) VALUES
                ('left_hand_raised', 0),
                ('right_hand_raised', 0),
                ('both_hands_raised', 0),
                ('no_detection', 0);

            -- Session info
            CREATE TABLE IF NOT EXISTS session (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                started_at REAL NOT NULL,
                total_chunks INTEGER DEFAULT 0,
                total_detections INTEGER DEFAULT 0
            );
        """)


def reset_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Reset all data (for demo restart)."""
    with get_db(db_path) as conn:
        conn.executescript("""
            DELETE FROM detections;
            DELETE FROM pipeline_state;
            DELETE FROM session;
            UPDATE counts SET count = 0, last_detected_at = NULL;
        """)


def start_session(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Start a new demo session."""
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO session (id, started_at, total_chunks, total_detections)
            VALUES (1, ?, 0, 0)
        """, (datetime.now().timestamp(),))


def record_detection(
    category: str,
    filename: str,
    confidence: Optional[float] = None,
    processing_time_ms: Optional[float] = None,
    db_path: Path = DEFAULT_DB_PATH
) -> int:
    """
    Record a detection event.
    Returns the detection ID.
    """
    timestamp = datetime.now().timestamp()

    with get_db(db_path) as conn:
        # Insert detection event
        cursor = conn.execute("""
            INSERT INTO detections (timestamp, category, filename, confidence, processing_time_ms)
            VALUES (?, ?, ?, ?, ?)
        """, (timestamp, category, filename, confidence, processing_time_ms))
        detection_id = cursor.lastrowid

        # Update counts
        conn.execute("""
            UPDATE counts
            SET count = count + 1, last_detected_at = ?
            WHERE category = ?
        """, (timestamp, category))

        # Update session stats
        conn.execute("""
            UPDATE session
            SET total_chunks = total_chunks + 1,
                total_detections = total_detections + CASE WHEN ? != 'no_detection' THEN 1 ELSE 0 END
            WHERE id = 1
        """, (category,))

        return detection_id


def set_pipeline_stage(stage: int, db_path: Path = DEFAULT_DB_PATH, source: str = "local") -> None:
    """Set the current pipeline stage (1-4). Source is 'expanso' or 'local'."""
    with get_db(db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO pipeline_state (key, value, updated_at)
            VALUES ('current_stage', ?, CURRENT_TIMESTAMP)
        """, (str(stage),))
        conn.execute("""
            INSERT OR REPLACE INTO pipeline_state (key, value, updated_at)
            VALUES ('stage_source', ?, CURRENT_TIMESTAMP)
        """, (source,))


def get_pipeline_stage(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Get the current pipeline stage (0 if none)."""
    with get_db(db_path) as conn:
        row = conn.execute("""
            SELECT value FROM pipeline_state WHERE key = 'current_stage'
        """).fetchone()
        return int(row["value"]) if row else 0


def get_stage_source(db_path: Path = DEFAULT_DB_PATH) -> str:
    """Get the source of the current stage ('expanso' or 'local')."""
    with get_db(db_path) as conn:
        row = conn.execute("""
            SELECT value FROM pipeline_state WHERE key = 'stage_source'
        """).fetchone()
        return row["value"] if row else "local"


def get_counts(db_path: Path = DEFAULT_DB_PATH) -> dict:
    """Get all category counts."""
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT category, count, last_detected_at FROM counts").fetchall()
        return {row["category"]: {"count": row["count"], "last_detected_at": row["last_detected_at"]} for row in rows}


def get_recent_detections(limit: int = 10, db_path: Path = DEFAULT_DB_PATH) -> list[dict]:
    """Get recent detection events."""
    with get_db(db_path) as conn:
        rows = conn.execute("""
            SELECT id, timestamp, category, filename, confidence, processing_time_ms
            FROM detections
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]


def get_latest_detection(db_path: Path = DEFAULT_DB_PATH) -> Optional[dict]:
    """Get the most recent detection."""
    detections = get_recent_detections(limit=1, db_path=db_path)
    return detections[0] if detections else None


def get_session_stats(db_path: Path = DEFAULT_DB_PATH) -> dict:
    """Get current session statistics."""
    with get_db(db_path) as conn:
        session = conn.execute("SELECT * FROM session WHERE id = 1").fetchone()
        if not session:
            return {"started_at": None, "duration_seconds": 0, "total_chunks": 0, "total_detections": 0}

        started_at = session["started_at"]
        duration = datetime.now().timestamp() - started_at if started_at else 0

        return {
            "started_at": started_at,
            "duration_seconds": duration,
            "total_chunks": session["total_chunks"],
            "total_detections": session["total_detections"],
            "detections_per_minute": (session["total_detections"] / duration * 60) if duration > 0 else 0,
        }


def get_full_stats(db_path: Path = DEFAULT_DB_PATH) -> dict:
    """Get comprehensive stats for dashboard."""
    return {
        "stage": get_pipeline_stage(db_path),
        "stage_source": get_stage_source(db_path),
        "counts": get_counts(db_path),
        "session": get_session_stats(db_path),
        "latest": get_latest_detection(db_path),
        "recent": get_recent_detections(limit=8, db_path=db_path),
    }


if __name__ == "__main__":
    # Test the database
    import os
    test_db = Path("/tmp/test_pipeline.db")
    if test_db.exists():
        os.remove(test_db)

    print("Initializing database...")
    init_db(test_db)

    print("Starting session...")
    start_session(test_db)

    print("Recording detections...")
    record_detection("left_hand_raised", "chunk_001.mp4", 0.95, 45.2, test_db)
    record_detection("right_hand_raised", "chunk_002.mp4", 0.88, 42.1, test_db)
    record_detection("both_hands_raised", "chunk_003.mp4", 0.92, 48.5, test_db)
    record_detection("no_detection", "chunk_004.mp4", None, 38.0, test_db)

    print("Setting pipeline stage...")
    set_pipeline_stage(2, test_db)

    print("\nFull stats:")
    import json
    print(json.dumps(get_full_stats(test_db), indent=2, default=str))

    print("\nDatabase test complete!")
    os.remove(test_db)
