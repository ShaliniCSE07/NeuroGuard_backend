from models import get_user_results, save_baseline, get_baseline

BASELINE_SESSIONS = 3  # first 3 sessions = baseline window


def establish_baseline(user_id, game_type):
    """Compute baseline from the first N sessions if not yet saved."""
    existing = get_baseline(user_id, game_type)
    if existing:
        return existing

    results = get_user_results(user_id, game_type)
    if len(results) < BASELINE_SESSIONS:
        return None  # not enough data yet

    window = results[:BASELINE_SESSIONS]
    avg_score = sum(r["score"] for r in window) / len(window)
    avg_acc = sum(r["accuracy"] for r in window) / len(window)
    avg_time = sum(r["time_taken"] for r in window) / len(window)
    avg_mistakes = sum(r["mistakes"] for r in window) / len(window)

    save_baseline(user_id, game_type, avg_score, avg_acc,
                  avg_time, avg_mistakes, len(window))
    return get_baseline(user_id, game_type)


def auto_build_all_baselines(user_id):
    """Try to build baselines for every game type the user has played."""
    results = get_user_results(user_id)
    game_types = set(r["game_type"] for r in results)
    built = {}
    for gt in game_types:
        b = establish_baseline(user_id, gt)
        if b:
            built[gt] = b
    return built