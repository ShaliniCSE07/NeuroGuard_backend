from database import get_connection
import json


def insert_game_result(data: dict):
    """Insert one game result row (Member 1's format)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO game_results
        (user_id, game_type, score, accuracy, time_taken,
         difficulty_level, attempts, mistakes, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("user_id"),
        data.get("game_type"),
        data.get("score"),
        data.get("accuracy"),
        data.get("time_taken"),
        data.get("difficulty_level"),
        data.get("attempts"),
        data.get("mistakes"),
        data.get("timestamp"),
    ))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_user_results(user_id: str, game_type: str = None):
    conn = get_connection()
    cur = conn.cursor()
    if game_type:
        cur.execute(
            "SELECT * FROM game_results WHERE user_id=? AND game_type=? ORDER BY timestamp ASC",
            (user_id, game_type),
        )
    else:
        cur.execute(
            "SELECT * FROM game_results WHERE user_id=? ORDER BY timestamp ASC",
            (user_id,),
        )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def save_baseline(user_id, game_type, avg_score, avg_accuracy,
                  avg_time, avg_mistakes, sessions):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO baselines
        (user_id, game_type, avg_score, avg_accuracy, avg_time_taken,
         avg_mistakes, sessions_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, game_type) DO UPDATE SET
            avg_score=excluded.avg_score,
            avg_accuracy=excluded.avg_accuracy,
            avg_time_taken=excluded.avg_time_taken,
            avg_mistakes=excluded.avg_mistakes,
            sessions_count=excluded.sessions_count,
            established_at=CURRENT_TIMESTAMP
    """, (user_id, game_type, avg_score, avg_accuracy,
          avg_time, avg_mistakes, sessions))
    conn.commit()
    conn.close()


def get_baseline(user_id, game_type):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM baselines WHERE user_id=? AND game_type=?",
        (user_id, game_type),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None