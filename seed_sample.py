"""
Run: python seed_sample.py
Creates 8 sessions for U001 to test baseline + radar.
Drop the last 3 sessions to simulate decline -> radar should flag it.
"""
import json
from database import init_db
from models import insert_game_result, get_user_results

SAMPLE = [
    # Baseline sessions (first 3)
    {"user_id":"U001","game_type":"memory_matching","score":9,"accuracy":80.0,"time_taken":90,"difficulty_level":2,"attempts":11,"mistakes":3,"timestamp":"2026-11-10T10:00:00Z"},
    {"user_id":"U001","game_type":"memory_matching","score":10,"accuracy":82.0,"time_taken":88,"difficulty_level":2,"attempts":12,"mistakes":2,"timestamp":"2026-11-12T10:00:00Z"},
    {"user_id":"U001","game_type":"memory_matching","score":9,"accuracy":78.0,"time_taken":92,"difficulty_level":2,"attempts":11,"mistakes":3,"timestamp":"2026-11-14T10:00:00Z"},
    # Recent sessions (simulated decline)
    {"user_id":"U001","game_type":"memory_matching","score":6,"accuracy":60.0,"time_taken":120,"difficulty_level":2,"attempts":14,"mistakes":7,"timestamp":"2026-11-15T10:00:00Z"},
    {"user_id":"U001","game_type":"memory_matching","score":5,"accuracy":55.0,"time_taken":125,"difficulty_level":2,"attempts":15,"mistakes":8,"timestamp":"2026-11-16T10:00:00Z"},
    {"user_id":"U001","game_type":"memory_matching","score":6,"accuracy":58.0,"time_taken":118,"difficulty_level":2,"attempts":14,"mistakes":7,"timestamp":"2026-11-17T10:00:00Z"},
    # One more strong run to test another game
    {"user_id":"U001","game_type":"number_recall","score":8,"accuracy":75.0,"time_taken":95,"difficulty_level":1,"attempts":10,"mistakes":2,"timestamp":"2026-11-18T10:00:00Z"},
]

if __name__ == "__main__":
    init_db()
    existing = get_user_results("U001")
    if existing:
        print(f"[seed] U001 already has {len(existing)} results — skipping.")
    else:
        for row in SAMPLE:
            insert_game_result(row)
        print(f"[seed] Inserted {len(SAMPLE)} results for U001.")
    print("[seed] Done. Run: python app.py")