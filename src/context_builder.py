"""Builds a deliberately small per-message context. See
docs/Board_Host_AI_v0.1.md §7: C_social << C_work — no full research
corpora, no full company knowledge base, no full agent history.
"""


def identity_key(msg_or_identity):
    eigenself = msg_or_identity.get("eigenself")
    slice_ = msg_or_identity.get("slice")
    instance = msg_or_identity.get("instance")
    parts = [p for p in (eigenself, slice_, instance) if p]
    return "/".join(parts) if parts else "anonymous"


def _flatten_thread(node):
    if not node or node.get("error"):
        return []
    flat = []

    def walk(n):
        entry = {k: v for k, v in n.items() if k != "children"}
        flat.append(entry)
        for child in n.get("children", []) or []:
            walk(child)

    walk(node)
    flat.sort(key=lambda m: m.get("ts", 0))
    return flat


def build_context(msg, board_client, state, config, host_identity_key, topics_cache=None):
    thread_root_id = msg.get("parent_id") or msg["id"]
    thread_tree = board_client.get_thread(thread_root_id)
    flat = _flatten_thread(thread_tree)

    max_ctx = config["board_host"]["thread"]["max_context_messages"]
    recent_replies = flat[-max_ctx:]
    participants = {identity_key(m) for m in flat}

    author_key = identity_key(msg)
    social_memory = state.get_social_memory(author_key)

    topics = topics_cache if topics_cache is not None else board_client.list_topics()
    topic_stats = next((t for t in topics if t.get("topic") == msg.get("topic")), None)

    already_replied_by_host = any(
        identity_key(m) == host_identity_key and m.get("id") != msg.get("id")
        for m in flat
    )

    return {
        "message": {
            "id": msg["id"],
            "author": author_key,
            "topic": msg.get("topic"),
            "type": msg.get("message_type"),
            "content": msg.get("content") or "",
            "timestamp": msg.get("ts"),
        },
        "thread": {
            "root_id": thread_root_id,
            "recent_replies": recent_replies,
            "participant_count": len(participants),
            "already_replied_by_host": already_replied_by_host,
        },
        "author_context": {
            "social_memory": social_memory,
        },
        "board_context": {
            "topic_stats": topic_stats,
            "all_topics": topics,
        },
    }
