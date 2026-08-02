"""Host Decision Policy. See docs/Board_Host_AI_v0.1.md §8 for the
heuristic scoring model (engineering guide, not "quantified emotion") and
§12 for loop_guard interaction.

Also folds in behavioral topic-diversity guidance ("多房間"), scoped per
Neo's 2026-08-02 direction: Board Host actively favors under-served
topics and mildly discounts topics it has been replying in a lot, rather
than always piling onto whatever's busiest. No new room infrastructure —
just a scoring adjustment plus a small, budgeted proactive-nudge path.
"""

import re

_QUESTION_MARKERS = ("?", "？")
_INVITE_PHRASES = (
    "what do you think",
    "curious",
    "anyone",
    "any thoughts",
    "would love to hear",
    "有人",
    "你觉得",
    "你覺得",
    "好奇",
    "想聽聽",
    "想聽聽看",
)
_NOVEL_TYPES = {"suggestion", "extension", "objection", "correction"}
_DEEP_TYPES = {"suggestion", "objection", "correction"}
_DEEP_KEYWORDS = re.compile(r"\b(why|prove|philosoph|research|hypothesis|counterexample)\b", re.I)

WEIGHTS = {
    "q": 0.25,
    "n": 0.15,
    "sc": 0.20,
    "d": 0.20,
    "r": 0.20,
    "f": 0.30,
    "l": 0.50,
}

SKIP_THRESHOLD = 0.30
DEEP_THRESHOLD = 0.55

# Topic-diversity adjustments are meant to be a nudge between otherwise
# comparable candidates, not something that alone should flip a genuinely
# content-free message from skip to reply. SKIP_THRESHOLD must stay
# comfortably above the "floor" score a maximally-boring comment gets
# (novelty 0.5 + discussable/reply-starved floors of 0.2 each), so a
# lone topic-diversity bonus can't manufacture engagement from nothing.


def _signal_question(content):
    return 1.0 if any(m in content for m in _QUESTION_MARKERS) else 0.0


def _signal_novelty(msg_type):
    return 1.0 if msg_type in _NOVEL_TYPES else 0.5


def _signal_social_invite(content):
    lowered = content.lower()
    return 1.0 if any(p in lowered for p in _INVITE_PHRASES) else 0.0


def _signal_discussable(content):
    length = len(content.strip())
    if length >= 400:
        return 1.0
    if length >= 120:
        return 0.6
    return 0.2


def _signal_reply_starved(thread_ctx):
    if thread_ctx["participant_count"] <= 1:
        return 1.0
    if thread_ctx["participant_count"] <= 2:
        return 0.5
    return 0.2


def _signal_freq_limited(social_memory, now_ts, cooldown_minutes):
    last = social_memory.get("last_interaction")
    if last is None:
        return 0.0
    minutes_since = (now_ts - last) / 60000.0
    return 1.0 if minutes_since < cooldown_minutes else 0.0


def _topic_diversity_adjustment(topic, state, config, now_ts):
    cfg = config.get("topic_diversity", {})
    if not cfg.get("enabled"):
        return 0.0

    adjustment = 0.0
    topic_key = topic or ""

    recent_log = state.host_reply_log()
    hot_window = cfg.get("hot_topic_window_replies", 3)
    recent_topics = [entry["topic"] for entry in recent_log[-hot_window:]]
    if recent_topics.count(topic_key) >= 2:
        adjustment -= cfg.get("hot_topic_reply_penalty", 0.35)

    visits = state.topic_visits()
    visit = visits.get(topic_key)
    scan_interval_minutes = config["board_host"]["scan_interval_minutes"]
    cold_runs = cfg.get("cold_topic_min_runs_since_visit", 2)
    cold_ms = scan_interval_minutes * cold_runs * 60000
    if visit is None or (now_ts - visit.get("last_visit_ts", 0)) >= cold_ms:
        adjustment += cfg.get("cold_topic_bonus", 0.25)

    return adjustment


def score_candidate(context, state, config, now_ts):
    message = context["message"]
    thread = context["thread"]
    social_memory = context["author_context"]["social_memory"]
    content = message["content"]

    q = _signal_question(content)
    n = _signal_novelty(message["type"])
    sc = _signal_social_invite(content)
    d = _signal_discussable(content)
    r = _signal_reply_starved(thread)
    f = _signal_freq_limited(
        social_memory, now_ts, config["board_host"]["social"]["same_author_cooldown_minutes"]
    )
    loop_risk = 1.0 if thread["already_replied_by_host"] else 0.0

    score = (
        WEIGHTS["q"] * q
        + WEIGHTS["n"] * n
        + WEIGHTS["sc"] * sc
        + WEIGHTS["d"] * d
        + WEIGHTS["r"] * r
        - WEIGHTS["f"] * f
        - WEIGHTS["l"] * loop_risk
    )
    score += _topic_diversity_adjustment(message["topic"], state, config, now_ts)

    return score


def decide(context, state, config, now_ts):
    """Returns {action, length_tier, reason, score, target_message_id, topic}.

    action in {"skip", "reply"}. length_tier in {"L0","L1","L2","L3"} —
    L1/L2/L3 map to the whitepaper's reply-length tiers (§10); the LLM
    prompt (see responder.py) is told which tier to aim for so replies
    aren't uniformly the same shape (helps satisfy T6 non-template).
    """
    message = context["message"]
    score = score_candidate(context, state, config, now_ts)

    if score < SKIP_THRESHOLD:
        return {
            "action": "skip",
            "length_tier": "L0",
            "reason": f"score {score:.2f} below skip threshold",
            "score": score,
            "target_message_id": message["id"],
            "topic": message["topic"],
        }

    is_deep = (
        message["type"] in _DEEP_TYPES
        and len(message["content"]) > 500
        and bool(_DEEP_KEYWORDS.search(message["content"]))
    )
    if is_deep and score >= DEEP_THRESHOLD:
        tier = "L3"
    elif score >= DEEP_THRESHOLD:
        tier = "L2"
    else:
        tier = "L1"

    return {
        "action": "reply",
        "length_tier": tier,
        "reason": f"score {score:.2f}",
        "score": score,
        "target_message_id": message["id"],
        "topic": message["topic"],
    }


def decide_proactive_nudge(state, board_client, config, now_ts, host_identity_key):
    """Budgeted, low-frequency proactive post into an under-served topic
    when no reply candidate stood out this run. This is a deliberate,
    small extension beyond the whitepaper's strict v0.1 scope (which
    reserves self-initiated posts for v0.2) — folded in per Neo's
    2026-08-02 "多房間" direction, kept as behavior only (no new
    infrastructure) and tightly budgeted.
    """
    cfg = config.get("topic_diversity", {}).get("proactive_nudge", {})
    if not cfg.get("enabled"):
        return None

    nudges_today = [
        nu for nu in state.proactive_nudges() if (now_ts - nu["ts"]) < 24 * 3600 * 1000
    ]
    if len(nudges_today) >= cfg.get("max_per_day", 1):
        return None

    if nudges_today:
        hours_since_last = (now_ts - nudges_today[-1]["ts"]) / 3600000.0
        if hours_since_last < cfg.get("min_hours_since_last_nudge", 12):
            return None

    topics = board_client.list_topics()
    if not topics:
        return None

    visits = state.topic_visits()

    def staleness(t):
        visit = visits.get(t["topic"])
        return 0 if visit is None else visit.get("last_visit_ts", 0)

    candidates = sorted(topics, key=staleness)
    for topic in candidates:
        if topic.get("message_count", 0) < 1:
            continue
        return {
            "action": "nudge",
            "topic": topic["topic"],
            "reason": "topic diversity: quiet topic with existing content, no recent host visit",
            "topic_stats": topic,
        }
    return None
