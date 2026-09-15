import sqlite3
from pathlib import Path

# 데이터베이스 파일 위치
DB_PATH = Path(__file__).resolve().parent / "safety.db"


def init_db():
    # 파일이 없으면 자동으로 생성
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                equipment TEXT NOT NULL,
                reviewed INTEGER NOT NULL DEFAULT 0
                    CHECK (reviewed IN (0, 1)),
                image_path TEXT
            )
        """)


if __name__ == "__main__":
    init_db()
    print(f"데이터베이스 준비 완료: {DB_PATH}")