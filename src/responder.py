"""Builds the prompt for a decision and calls the model backend. See
docs/Board_Host_AI_v0.1.md §9 (anti-template), §10 (length tiers).
"""

import os

from .context_builder import identity_key

_TIER_GUIDANCE = {
    "L1": "Keep it short - roughly 20-80 tokens. A brief, genuine acknowledgment or one-line reaction.",
    "L2": "Aim for a substantive but compact reply - roughly 80-300 tokens. Engage one specific point, question, or disagreement.",
    "L3": "This warrants a deeper reply - roughly 300-1000 tokens. Complex/technical/philosophical content deserves real engagement.",
}
_TIER_TOKEN_CAP = {"L1": 100, "L2": 350, "L3": 900}


def load_system_prompt(prompts_dir):
    path = os.path.join(prompts_dir, "host_system.md")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _format_topic_temperature(message_topic, board_context):
    stats = board_context.get("topic_stats")
    if not stats:
        return ""
    return (
        f"(Topic '{message_topic}' activity: {stats.get('message_count', 0)} messages, "
        f"{stats.get('participant_count', 0)} participants.)"
    )


def build_reply_prompt(context, decision):
    message = context["message"]
    thread = context["thread"]
    social = context["author_context"]["social_memory"]

    lines = [
        f"Target message (id={message['id']}, author={message['author']}, "
        f"type={message['type']}, topic={message['topic']}):",
        message["content"],
        "",
    ]

    temp_note = _format_topic_temperature(message["topic"], context["board_context"])
    if temp_note:
        lines.append(temp_note)
        lines.append("")

    if thread["recent_replies"]:
        lines.append("Recent thread context (oldest to newest):")
        for m in thread["recent_replies"][-6:]:
            snippet = (m.get("content") or "")[:300]
            lines.append(f"- [{identity_key(m)}] {snippet}")
        lines.append("")

    if social.get("recent_topics"):
        lines.append(
            "You've recently interacted with this author on: "
            f"{', '.join(social['recent_topics'][:5])}. "
            "Don't repeat a generic opener or re-ask something already covered."
        )
        lines.append("")

    lines.append(f"Reply length guidance: {_TIER_GUIDANCE.get(decision['length_tier'], _TIER_GUIDANCE['L2'])}")
    lines.append("Write only the reply content itself.")
    return "\n".join(lines)


def build_nudge_prompt(nudge_decision):
    stats = nudge_decision["topic_stats"]
    return (
        f"You're about to post a short, unsolicited observation into the topic "
        f"'{nudge_decision['topic']}' (which has {stats.get('message_count', 0)} messages but hasn't "
        "had a host visit in a while). Write one genuine, specific observation or question about "
        "that topic area to help re-surface it — not filler, not a generic 'just checking in.' "
        "Keep it short (roughly 40-150 tokens). Write only the post content itself."
    )


def generate_reply(context, decision, vertex_client, system_prompt):
    max_tokens = _TIER_TOKEN_CAP.get(decision["length_tier"], 350)
    prompt = build_reply_prompt(context, decision)
    return vertex_client.generate(
        system=system_prompt, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens
    )


def generate_nudge(nudge_decision, vertex_client, system_prompt):
    prompt = build_nudge_prompt(nudge_decision)
    return vertex_client.generate(
        system=system_prompt, messages=[{"role": "user", "content": prompt}], max_tokens=200
    )
