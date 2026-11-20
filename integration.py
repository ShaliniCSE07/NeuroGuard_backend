from models import insert_game_result, get_user_results
from baseline import establish_baseline
import personalisation

def ingest_result(data: dict):
    required = ["user_id", "game_type", "score", "accuracy", "time_taken"]
    for field in required:
        if field not in data:
            return False, f"Missing field: {field}", None

    insert_game_result(data)
    baseline = establish_baseline(data["user_id"], data["game_type"])
    return True, "stored", baseline

def get_recommendations(user_id, radar):
    """Uses Member 3's AI engine."""
    try:
        # 1. Fetch all past game results for this user from your database
        results = get_user_results(user_id)
        
        if not results:
            return []

        # 2. Pass results to Member 3's AI
        ai_report = personalisation.analyse(results)
        
        # 3. Format their output to match what your dashboard expects
        formatted_recs = []
        for r in ai_report.get("recommendations", []):
            formatted_recs.append({
                "game_type": r.get("activity"),
                "recommendation": f"Try {r.get('title')} at Level {r.get('suggested_level')}.",
                "reason": r.get("reason")
            })
        return formatted_recs
        
    except Exception as e:
        print(f"AI Error: {e}")
        # Fallback if their AI crashes
        return [{"game_type": "memory_matching", "recommendation": "Keep playing!", "reason": "Fallback mode."}]