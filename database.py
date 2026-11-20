import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "neuroguard.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Game results (matches Member 1's output format exactly)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS game_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            game_type TEXT NOT NULL,
            score INTEGER,
            accuracy REAL,
            time_taken INTEGER,
            difficulty_level INTEGER,
            attempts INTEGER,
            mistakes INTEGER,
            timestamp TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Cognitive baseline per user + game type
    cur.execute("""
        CREATE TABLE IF NOT EXISTS baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            game_type TEXT NOT NULL,
            avg_score REAL,
            avg_accuracy REAL,
            avg_time_taken REAL,
            avg_mistakes REAL,
            sessions_count INTEGER,
            established_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, game_type)
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Initialized at", DB_PATH)