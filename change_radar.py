from models import get_user_results, get_baseline

# Thresholds — a change is "persistent" if it repeats this many times
PERSISTENT_WINDOW = 3
SCORE_DROP_THRESHOLD = 0.15     # 15% drop from baseline
ACCURACY_DROP_THRESHOLD = 10.0  # 10 percentage points
TIME_INCREASE_THRESHOLD = 0.25  # 25% slower
MISTAKE_INCREASE_THRESHOLD = 0.30


def _pct_change(old, new):
    if old == 0:
        return 0
    return ((new - old) / abs(old)) * 100


def analyze_change(user_id, game_type):
    """
    Compare recent sessions with the personal baseline.
    Returns a dict the dashboard can display directly.
    """
    baseline = get_baseline(user_id, game_type)
    results = get_user_results(user_id, game_type)
    if not baseline or not results:
        return {"status": "insufficient_data"}

    # last N sessions
    recent = results[-PERSISTENT_WINDOW:]
    if len(recent) < PERSISTENT_WINDOW:
        return {"status": "insufficient_data"}

    score_pct = _pct_change(baseline["avg_score"],
                            sum(r["score"] for r in recent) / len(recent))
    acc_pct = _pct_change(baseline["avg_accuracy"],
                          sum(r["accuracy"] for r in recent) / len(recent))
    time_pct = _pct_change(baseline["avg_time_taken"],
                           sum(r["time_taken"] for r in recent) / len(recent))
    mistake_pct = _pct_change(baseline["avg_mistakes"],
                              sum(r["mistakes"] for r in recent) / len(recent))

    flags = []
    if score_pct < -SCORE_DROP_THRESHOLD * 100:
        flags.append("score_decline")
    if acc_pct < -ACCURACY_DROP_THRESHOLD:
        flags.append("accuracy_decline")
    if time_pct > TIME_INCREASE_THRESHOLD * 100:
        flags.append("response_time_slowing")
    if mistake_pct > MISTAKE_INCREASE_THRESHOLD * 100:
        flags.append("mistakes_increasing")

    if len(flags) >= 2:
        severity = "attention"
        message = ("Persistent changes detected in multiple areas. "
                   "Consider a professional evaluation.")
    elif len(flags) == 1:
        severity = "watch"
        message = "A mild persistent change was noticed. Keep monitoring."
    else:
        severity = "stable"
        message = "Performance is stable relative to your personal baseline."

    return {
        "status": "ok",
        "game_type": game_type,
        "baseline": baseline,
        "recent_average": {
            "score": sum(r["score"] for r in recent) / len(recent),
            "accuracy": sum(r["accuracy"] for r in recent) / len(recent),
            "time_taken": sum(r["time_taken"] for r in recent) / len(recent),
            "mistakes": sum(r["mistakes"] for r in recent) / len(recent),
        },
        "changes_pct": {
            "score": round(score_pct, 1),
            "accuracy": round(acc_pct, 1),
            "time_taken": round(time_pct, 1),
            "mistakes": round(mistake_pct, 1),
        },
        "flags": flags,
        "severity": severity,
        "message": message,
    }


def full_radar(user_id):
    """Radar across all game types the user has played."""
    results = get_user_results(user_id)
    game_types = sorted(set(r["game_type"] for r in results))
    return {
        "user_id": user_id,
        "games": {gt: analyze_change(user_id, gt) for gt in game_types},
    }