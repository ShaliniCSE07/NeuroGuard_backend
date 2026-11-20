"""AI Personalisation - simple, explainable rule-based logic.

Input:  Member 1 game-result JSON (exact format, no field changes).
Output: per-domain performance summary, next difficulty per game, activity
        recommendations - each with a plain-language reason.

This is a cognitive-wellness aid. It does NOT diagnose, screen or treat, and
its wording intentionally avoids clinical conclusions.
"""
import math
import re
from datetime import datetime, timezone
from statistics import mean

REQUIRED_FIELDS = {
    "user_id": str,
    "game_type": str,
    "score": (int, float),
    "accuracy": (int, float),
    "time_taken": (int, float),
    "difficulty_level": int,
    "attempts": int,
    "mistakes": int,
    "timestamp": str,
}

# game_type -> cognitive domain. Aliases cover naming variations from Member 1.
# Lookup is case/space/hyphen-insensitive ("Memory Matching", "memory-matching" both work);
# the stored game_type value itself is never changed.
GAME_DOMAINS = {
    "memory_matching": "memory",
    "memory_match": "memory",
    "card_matching": "memory",
    "sequence_recall": "working_memory",
    "number_recall": "working_memory",
    "number_sequence_recall": "working_memory",
    "number_sequence": "working_memory",
    "sequence_memory": "working_memory",
    "pattern_recognition": "attention",
    "attention_pattern": "attention",
    "attention_pattern_recognition": "attention",
    "pattern_attention": "attention",
    "attention": "attention",
    "memory_recall": "personal_memory",  # produced by this module's Memory-to-Game
}
MIN_SESSIONS_TO_COMPARE = 3   # an area needs this many sessions before it is called weakest/strongest
PRACTICE_BELOW = 70.0         # "gentle practice" wording only below this recent accuracy
MAX_BATCH = 1000              # max results per import request
DOMAIN_LABELS = {
    "memory": "Memory",
    "working_memory": "Number & Sequence Recall",
    "attention": "Attention & Patterns",
    "personal_memory": "Personal Memories",
    "other": "Other activities",
}
DOMAIN_ACTIVITY = {
    "memory": ("memory_matching", "Memory Matching"),
    "working_memory": ("sequence_recall", "Number / Sequence Recall"),
    "attention": ("pattern_recognition", "Attention & Pattern Recognition"),
    "personal_memory": ("memory_recall", "Family Photo Memories"),
}

MIN_LEVEL, MAX_LEVEL = 1, 5
WINDOW = 3             # recent sessions considered for difficulty changes
UP_ACCURACY = 80.0     # step up when recent average accuracy >= this ...
UP_MIN_SESSIONS = 3    # ... over at least this many sessions at the current level
DOWN_ACCURACY = 50.0   # ease back when recent average accuracy < this ...
DOWN_MIN_SESSIONS = 2  # ... over at least this many sessions (one bad day never changes level)

DISCLAIMER = ("NEUROGUARD supports cognitive wellness. These suggestions are based on game "
              "activity only and are not a medical assessment or diagnosis. Please speak to a "
              "healthcare professional about any health concerns.")


class ValidationError(ValueError):
    pass


def validate_result(data):
    """Validate one Member 1 result. Returns a clean dict with exactly the 9 fields."""
    if not isinstance(data, dict):
        raise ValidationError("Each game result must be a JSON object.")
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise ValidationError(f"Missing field(s): {', '.join(missing)}")
    clean = {}
    for field, typ in REQUIRED_FIELDS.items():
        val = data[field]
        if isinstance(val, bool) or not isinstance(val, typ):
            raise ValidationError(f"Field '{field}' has the wrong type.")
        clean[field] = val
    if not clean["user_id"].strip() or not clean["game_type"].strip():
        raise ValidationError("user_id and game_type must not be empty.")
    if len(clean["user_id"]) > 64 or len(clean["game_type"]) > 64:
        raise ValidationError("user_id and game_type must be at most 64 characters.")
    for field in ("score", "accuracy", "time_taken"):
        if not math.isfinite(clean[field]):  # Python's JSON parser accepts NaN / Infinity
            raise ValidationError(f"{field} must be a finite number.")
    if not 0 <= clean["accuracy"] <= 100:
        raise ValidationError("accuracy must be between 0 and 100.")
    if clean["difficulty_level"] < 1:
        raise ValidationError("difficulty_level must be >= 1.")
    for field in ("score", "time_taken", "attempts", "mistakes"):
        if clean[field] < 0:
            raise ValidationError(f"{field} must not be negative.")
    if clean["mistakes"] > clean["attempts"]:
        raise ValidationError("mistakes cannot be greater than attempts.")
    parse_timestamp(clean["timestamp"])
    return clean


def parse_timestamp(ts):
    """Parse an ISO-8601 date-time into an aware UTC datetime (naive -> treated as UTC).
    Used for validation AND for sorting, so 'Z', '+05:30' and millisecond variants order correctly."""
    if not isinstance(ts, str) or "T" not in ts:
        raise ValidationError("timestamp must be an ISO-8601 date-time, e.g. 2026-11-18T10:30:00Z")
    try:
        dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("timestamp must be an ISO-8601 date-time, e.g. 2026-11-18T10:30:00Z") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sort_key(result):
    """Chronological sort key for stored results; unparseable legacy values sort first."""
    try:
        return parse_timestamp(result["timestamp"])
    except ValidationError:
        return datetime.min.replace(tzinfo=timezone.utc)


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def game_key(game_type):
    return re.sub(r"[\s\-]+", "_", str(game_type).strip().lower())


def domain_of(game_type):
    return GAME_DOMAINS.get(game_key(game_type), "other")


def _trend(results):
    """Compare last WINDOW sessions with the WINDOW before. Plain words only.
    If the difficulty level changed between the two windows, accuracy is not comparable
    (a harder level naturally scores lower), so no up/down trend is reported."""
    if len(results) < 2 * WINDOW:
        return "not_enough_data"
    recent_w, earlier_w = results[-WINDOW:], results[-2 * WINDOW:-WINDOW]
    levels = lambda w: {(game_key(r["game_type"]), r["difficulty_level"]) for r in w}  # noqa: E731
    if levels(recent_w) != levels(earlier_w):
        return "level_changed"
    recent = mean(r["accuracy"] for r in recent_w)
    earlier = mean(r["accuracy"] for r in earlier_w)
    diff = recent - earlier
    if diff >= 5:
        return "improving"
    if diff <= -5:
        return "lower_recently"
    return "steady"


MAX_LEVEL_BY_GAME = {"memory_recall": 3}


def next_difficulty(results):
    """Rule-based difficulty for ONE game_type. Results may be in any order.

    Gradual + explainable:
      * only the CONSECUTIVE run of sessions at the current level counts, so a level that was
        just changed must earn its own evidence before it changes again;
      * up   one level after >= 3 sessions averaging >= 80 %;
      * down one level after >= 2 sessions averaging <  50 %;
      * never more than one step; clamped to 1..max (memory_recall max 3);
      * every answer carries the rule applied and the evidence used.
    """
    if not results:
        return {"level": 1, "change": "start", "rule": "no_history",
                "reason": "Starting at the gentlest level.",
                "evidence": {"current_level": None, "sessions_considered": 0, "average_accuracy": None}}
    results = sorted(results, key=sort_key)
    max_level = MAX_LEVEL_BY_GAME.get(game_key(results[-1]["game_type"]), MAX_LEVEL)

    def level_of(r):
        return max(MIN_LEVEL, min(int(r["difficulty_level"]), max_level))

    current = level_of(results[-1])
    run = []
    for r in reversed(results):  # consecutive sessions at the current level, newest first
        if level_of(r) != current:
            break
        run.append(r)
    at_level = run[:WINDOW]
    avg = mean(r["accuracy"] for r in at_level)
    n = len(at_level)
    evidence = {"current_level": current, "sessions_considered": n, "average_accuracy": round(avg, 1)}
    s = "session" if n == 1 else "sessions"

    def out(level, change, rule, reason):
        return {"level": level, "change": change, "rule": rule, "reason": reason, "evidence": evidence}

    if avg >= UP_ACCURACY and current < max_level:
        if n >= UP_MIN_SESSIONS:
            return out(current + 1, "up", "step_up",
                       f"Average accuracy {avg:.0f}% over the last {n} sessions at level {current} "
                       f"- ready for a small step up.")
        return out(current, "same", "waiting_for_evidence",
                   f"Going well ({avg:.0f}% over {n} {s}). Staying at level {current} until "
                   f"{UP_MIN_SESSIONS} sessions are completed at this level.")
    if avg < DOWN_ACCURACY and current > MIN_LEVEL:
        if n >= DOWN_MIN_SESSIONS:
            return out(current - 1, "down", "ease_back",
                       f"Average accuracy {avg:.0f}% over the last {n} sessions at level {current} "
                       f"- easing back one level to keep the activity enjoyable.")
        return out(current, "same", "waiting_for_evidence",
                   f"Accuracy {avg:.0f}% in {n} {s} at level {current}. Staying at this level for "
                   f"now - one session alone is not enough to change it.")
    if current >= max_level and avg >= UP_ACCURACY:
        return out(current, "same", "at_max_level", f"Doing well ({avg:.0f}%) at the highest level.")
    if current <= MIN_LEVEL and avg < DOWN_ACCURACY:
        return out(current, "same", "at_min_level",
                   f"Recent accuracy {avg:.0f}% - already at the gentlest level.")
    return out(current, "same", "keep",
               f"Recent accuracy {avg:.0f}% - level {current} feels about right.")


def analyse(results):
    """Full personalisation report for one user's results (any order)."""
    results = sorted(results, key=sort_key)
    by_game, by_domain = {}, {}
    for r in results:
        by_game.setdefault(r["game_type"], []).append(r)
        by_domain.setdefault(domain_of(r["game_type"]), []).append(r)

    domains = []
    for d, rs in by_domain.items():
        accs = [r["accuracy"] for r in rs]
        recent = rs[-WINDOW:]
        domains.append({
            "domain": d,
            "label": DOMAIN_LABELS.get(d, d),
            "sessions": len(rs),
            "average_accuracy": round(mean(accs), 1),
            "recent_accuracy": round(mean(r["accuracy"] for r in recent), 1),
            "average_time_taken": round(mean(r["time_taken"] for r in rs), 1),
            "recent_time_taken": round(mean(r["time_taken"] for r in recent), 1),
            "trend": _trend(rs),
            "enough_data": len(rs) >= MIN_SESSIONS_TO_COMPARE,
            "last_played": rs[-1]["timestamp"],
        })
    domains.sort(key=lambda x: x["recent_accuracy"])

    difficulty = {g: {**next_difficulty(rs), "domain": domain_of(g)} for g, rs in by_game.items()}
    return {
        "total_sessions": len(results),
        "domains": domains,
        "difficulty": difficulty,
        "recommendations": recommend(domains, difficulty, by_game),
        "disclaimer": DISCLAIMER,
    }


def recommend(domains, difficulty, by_game=None):
    """Pick up to 4 friendly activity suggestions, each with a reason.

    The recommended `activity` is the game_type the user ACTUALLY played in that domain
    (most recent), so ids like 'number_recall' from Member 1 match their own game and its
    difficulty entry. Default ids are used only for domains never played."""
    recs = []
    played = {d["domain"] for d in domains}
    latest_game = {}
    for game, rs in (by_game or {}).items():
        dom = domain_of(game)
        if dom == "other":
            continue
        last = max(rs, key=sort_key)
        if dom not in latest_game or sort_key(last) > latest_game[dom][1]:
            latest_game[dom] = (game, sort_key(last))

    def add(domain, reason, priority, kind):
        default_game, name = DOMAIN_ACTIVITY.get(domain, (domain, DOMAIN_LABELS.get(domain, domain)))
        game_type = latest_game.get(domain, (default_game,))[0]
        if any(r["activity"] == game_type for r in recs):
            return
        level = difficulty.get(game_type, {}).get("level", 1)
        recs.append({"activity": game_type, "title": name, "suggested_level": level,
                     "reason": reason, "priority": priority, "kind": kind})

    # Only areas with enough sessions are compared, so 1-2 sessions never produce a
    # "weakest"/"strongest" label (insufficient data must not look like a finding).
    known = [d for d in domains if d["domain"] in DOMAIN_ACTIVITY]
    comparable = [d for d in known if d["enough_data"]]
    if comparable:
        weakest = comparable[0]
        if weakest["recent_accuracy"] < PRACTICE_BELOW:
            add(weakest["domain"],
                f"A little extra gentle practice could help here (recent accuracy "
                f"{weakest['recent_accuracy']:.0f}% over the last {min(WINDOW, weakest['sessions'])} "
                f"sessions - the lowest of the activities played).", 1, "practice")
        if len(comparable) > 1:
            strongest = comparable[-1]
            if strongest["domain"] != weakest["domain"]:
                add(strongest["domain"],
                    f"An activity they're enjoying success with (recent accuracy "
                    f"{strongest['recent_accuracy']:.0f}%) - great for confidence.", 3, "confidence")
    for d in comparable:
        if d["trend"] == "lower_recently":
            add(d["domain"],
                "Scores have been a bit lower over the last 3 sessions than the 3 before, at the "
                "same level - a short, relaxed session may feel nicer. If you notice lasting "
                "changes, consider discussing them with a healthcare professional.", 2, "lower_recently")
    for d in known:
        if not d["enough_data"]:
            add(d["domain"],
                f"Only {d['sessions']} session{'s' if d['sessions'] != 1 else ''} so far - "
                f"suggestions become personal after {MIN_SESSIONS_TO_COMPARE}.", 3, "building")

    for d in ("memory", "working_memory", "attention"):
        if d not in played:
            add(d, "Not tried yet - adds variety to the routine.", 4, "variety")

    add("personal_memory",
        "Looking at familiar photos together is a warm, social way to reminisce.", 2, "reminisce")

    recs.sort(key=lambda r: r["priority"])
    return recs[:4]


def memory_session_to_result(user_id, attempts, time_taken, difficulty_level, timestamp=None):
    """Convert a finished Memory-to-Game session into Member 1's exact nine-field format,
    so Member 2's baseline and Member 4's dashboard can treat it like any other game.

    Metric definitions (one row = one submitted answer; open 'reminisce' answers excluded):
        score    = correct answers
        mistakes = incorrect answers
        attempts = score + mistakes            (every answer is exactly one of the two)
        accuracy = score / attempts * 100      (0.0 only if attempts == 0, which callers refuse)
    Returns None when there are no scored answers - an empty session never produces a result.
    """
    scored = [a for a in attempts if a["question_type"] != "reminisce"]
    if not scored:
        return None
    score = sum(1 for a in scored if a["correct"])
    mistakes = len(scored) - score
    attempts_n = score + mistakes
    return {
        "user_id": user_id,
        "game_type": "memory_recall",
        "score": score,
        "accuracy": round(100.0 * score / attempts_n, 1),
        "time_taken": max(0, int(time_taken)),
        "difficulty_level": int(difficulty_level),
        "attempts": attempts_n,
        "mistakes": mistakes,
        "timestamp": timestamp or utc_now_iso(),
    }
