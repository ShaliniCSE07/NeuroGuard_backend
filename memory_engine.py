"""Memory-to-Game Engine.

Turns caregiver-entered memories (photo + name + relationship + description)
into gentle, personalised recall activities.

Question types
--------------
who           MCQ   "Who is in this photo?"
relationship  MCQ   "How is <name> related to you?"
place         MCQ   "Where was this photo taken?"        (only if place given)
year          MCQ   "Around which year was this?"         (only if year given)
name_recall   typed "Can you tell me this person's name?" (difficulty >= 3)
reminisce     open  "What do you remember about this day?" (always accepted)

Difficulty (1-3) controls the number of options and whether typed recall is used:
    1 -> 2 options,  2 -> 3 options,  3 -> 4 options + typed recall
Answer choices prefer the person's real family names/places, and relationship choices stay
within the same gender group (+ neutral), so questions are meaningful rather than guessable.
The issued questions/options are stored per session (activity_sessions) and answers are
verified server-side.
"""
import difflib
import random
import re
import unicodedata
from datetime import datetime

FALLBACK_NAMES = ["Meera", "Ravi", "Anita", "John", "Grace", "Arjun", "Lakshmi", "Peter", "Fatima", "David"]
# Relationship groups make answer choices plausible: "How is Raj related to you?" offers other
# male (or neutral) relationships, not "Daughter", which would give the answer away.
MALE_RELS = ["Husband", "Son", "Grandson", "Brother", "Father", "Grandfather", "Nephew", "Uncle"]
FEMALE_RELS = ["Wife", "Daughter", "Granddaughter", "Sister", "Mother", "Grandmother", "Niece", "Aunt"]
NEUTRAL_RELS = ["Friend", "Neighbour", "Cousin", "Grandchild", "Child", "Partner", "Carer"]
RELATIONSHIPS = MALE_RELS + FEMALE_RELS + NEUTRAL_RELS
FALLBACK_PLACES = ["The beach", "Our home", "The temple", "A wedding hall", "The park", "The market", "The garden"]
FIELD_LIMITS = {"person_name": 60, "relationship": 40, "description": 500, "place": 80}

ENCOURAGE_CORRECT = [
    "Wonderful! That's right.",
    "Yes, well remembered!",
    "Lovely - you got it.",
    "That's correct. Beautiful memory.",
]
ENCOURAGE_TRY_AGAIN = [
    "That's alright - let's look at the photo together.",
    "Good try. Take your time, there's no rush.",
    "Not quite, but you're doing well. Let's try a hint.",
]
ENCOURAGE_REVEAL = "That's okay. It was {answer}. Thank you for sharing this moment."

OPTIONS_BY_LEVEL = {1: 2, 2: 3, 3: 4}
MAX_TRIES = 2  # after this many wrong tries the answer is gently revealed and the question closes


def _norm(text):
    """Case/punctuation/space-insensitive key. Unicode-aware, so names written in any script
    (e.g. Tamil or Devanagari) are compared correctly instead of being stripped to ''."""
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    text = re.sub(r"[^\w\s]", "", text).replace("_", "")
    return re.sub(r"\s+", " ", text).strip()


def _rel_group(rel):
    key = _norm(rel)
    if key in {_norm(r) for r in MALE_RELS}:
        return MALE_RELS
    if key in {_norm(r) for r in FEMALE_RELS}:
        return FEMALE_RELS
    return None


def clamp_level(level):
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 1
    return max(1, min(3, level))


def _options(correct, pool, n, rng, preferred=()):
    """`correct` + (n-1) distinct distractors. `preferred` distractors (e.g. the names of the
    person's real family members) are used first, then the generic `pool`.
    De-duplicates case/punctuation-insensitively ("Priya" vs "priya") and drops the answer."""
    seen, distractors = {_norm(correct)}, []
    for group in (list(preferred), list(pool)):
        rng.shuffle(group)
        for p in group:
            key = _norm(p)
            if p and key and key not in seen:
                seen.add(key)
                distractors.append(p)
    opts = [correct] + distractors[: n - 1]
    rng.shuffle(opts)
    return opts


def correct_answer(memory, qtype):
    return {
        "who": memory["person_name"],
        "name_recall": memory["person_name"],
        "relationship": memory["relationship"],
        "place": memory.get("place") or "",
        "year": str(parse_year(memory.get("memory_year")) or ""),
    }.get(qtype)


def hints_for(memory, qtype):
    """Progressive hints: each one gives a bit more help."""
    name = memory["person_name"]
    desc = memory["description"]
    short_desc = desc if len(desc) <= 90 else desc[:87].rsplit(" ", 1)[0] + "..."
    rel = memory["relationship"]
    if qtype in ("who", "name_recall"):
        return [
            f"This is your {rel.lower()}.",
            f"Their name starts with \"{name[0].upper()}\".",
            f"Remember: {short_desc}",
        ]
    if qtype == "relationship":
        return [f"Think about the family photos with {name}.",
                f"It starts with \"{rel[0].upper()}\".",
                f"Remember: {short_desc}"]
    if qtype == "place":
        return [f"You were with {name}.", f"Remember: {short_desc}"]
    if qtype == "year":
        return [f"Think about when you were with {name}.", f"Remember: {short_desc}"]
    return [f"Look closely at {name} in the photo.", f"Remember: {short_desc}"]


MIN_YEAR = 1900


def parse_year(value):
    """Return a valid 4-digit year as int, or None (empty / '1990s' / 'long ago' / future)."""
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}", text):
        return None
    year = int(text)
    return year if MIN_YEAR <= year <= datetime.now().year else None


def _year_pool(year):
    """Plausible, distinct, non-future distractor years (always >= 3 when year is valid)."""
    y = parse_year(year)
    if y is None:
        return []
    now = datetime.now().year
    pool = [y + d for d in (-5, 5, -10, 10, -15, -20, 15, 20)]
    return [str(p) for p in pool if MIN_YEAR <= p <= now and p != y]


def build_questions(memory, all_memories, level=1, seed=None):
    """Build the question list for one memory."""
    level = clamp_level(level)
    n = OPTIONS_BY_LEVEL[level]
    rng = random.Random(f"{seed}-{memory['id']}")
    others = [m for m in all_memories if m["id"] != memory["id"]]

    # Real family names / places first (meaningful choices), generic fallbacks after.
    family_names = [m["person_name"] for m in others]
    family_places = [m.get("place") for m in others if m.get("place")]
    group = _rel_group(memory["relationship"])
    if group:  # keep choices plausible for the person's gender
        allowed = {_norm(r) for r in group + NEUTRAL_RELS}
        family_rels = [m["relationship"] for m in others if _norm(m["relationship"]) in allowed]
        rel_pool = group + NEUTRAL_RELS
    else:
        family_rels = [m["relationship"] for m in others]
        rel_pool = RELATIONSHIPS

    base = {"memory_id": memory["id"], "photo_url": f"/uploads/{memory['photo_filename']}"}
    qs = []

    def add(qtype, prompt, kind, options=None):
        # A multiple-choice question is only valid with >= 2 distinct options incl. the answer.
        if kind == "mcq":
            expected = correct_answer(memory, qtype)
            if len({_norm(o) for o in options or []}) < 2 or \
                    not any(_norm(o) == _norm(expected) for o in options):
                return
        qs.append({
            **base,
            "question_id": f"{memory['id']}:{qtype}",
            "question_type": qtype,
            "kind": kind,  # mcq | typed | open
            "prompt": prompt,
            "options": options or [],
            "hints": hints_for(memory, qtype),
        })

    if level >= 3:
        add("name_recall", "Can you tell me this person's name?", "typed")
    else:
        # "Who is in this photo?" also reads naturally for group photos (only one choice is pictured).
        add("who", "Who is in this photo?", "mcq",
            _options(memory["person_name"], FALLBACK_NAMES, n, rng, preferred=family_names))

    add("relationship", f"How is {memory['person_name']} related to you?", "mcq",
        _options(memory["relationship"], rel_pool, n, rng, preferred=family_rels))

    if memory.get("place"):
        add("place", "Where was this photo taken?", "mcq",
            _options(memory["place"], FALLBACK_PLACES, n, rng, preferred=family_places))

    if parse_year(memory.get("memory_year")) is not None and level >= 2:
        year = str(parse_year(memory["memory_year"]))
        add("year", "Around which year was this?", "mcq", _options(year, _year_pool(year), n, rng))

    add("reminisce", f"What do you remember about this moment with {memory['person_name']}?", "open")
    return qs


def build_session(memories, level=1, seed=None, max_memories=5):
    """Build a full activity session from several memories."""
    rng = random.Random(seed)
    chosen = list(memories)
    rng.shuffle(chosen)
    chosen = chosen[:max_memories]
    questions = []
    for m in chosen:
        questions.extend(build_questions(m, memories, level, seed))
    return {
        "difficulty_level": clamp_level(level),
        "instructions": "Look at the photo. Take your time. Tap 'Hint' any time you would like help.",
        "question_count": len(questions),
        "questions": questions,
    }


def name_matches(answer, expected, other_names=()):
    """Tolerant typed-name check: exact, first name only, or a small spelling slip (>= 75 %
    similar). An answer that is exactly ANOTHER family member's name is never accepted, so
    'Priyanka' does not count as 'Priya' when Priyanka is also in the family."""
    a, e = _norm(answer), _norm(expected)
    if not a:
        return False
    if a == e or a == e.split(" ")[0]:
        return True
    if any(a == _norm(o) or a == _norm(o).split(" ")[0] for o in other_names if _norm(o) != e):
        return False
    return difflib.SequenceMatcher(None, a, e).ratio() >= 0.75


def check_answer(memory, qtype, answer, attempt_number=1, rng=None, other_names=()):
    """Return (correct, feedback_dict). Never discouraging."""
    rng = rng or random.Random()
    if qtype == "reminisce":
        text = (answer or "").strip()
        msg = "Thank you for sharing that lovely memory." if text else "That's alright. Just enjoying the photo is wonderful."
        return True, {
            "correct": True,
            "message": msg,
            "story": memory["description"],
            "reveal": None,
        }

    expected = correct_answer(memory, qtype)
    if expected is None:
        raise ValueError(f"Unknown question type: {qtype}")

    if qtype == "name_recall":
        correct = name_matches(answer, expected, other_names)  # spelling slips are fine
    else:
        correct = _norm(answer) == _norm(expected)

    if correct:
        return True, {"correct": True, "message": rng.choice(ENCOURAGE_CORRECT),
                      "story": memory["description"], "reveal": expected}
    if attempt_number >= MAX_TRIES:
        return False, {"correct": False, "message": ENCOURAGE_REVEAL.format(answer=expected),
                       "story": memory["description"], "reveal": expected}
    return False, {"correct": False, "message": rng.choice(ENCOURAGE_TRY_AGAIN),
                   "story": None, "reveal": None}
