"""Prevents the Host from talking to itself. See
docs/Board_Host_AI_v0.1.md §12 — the hard rule:
Host Reply ⇏ Host auto-replies to its own reply again,
unless a new external AI joins the thread.
"""

from .context_builder import identity_key


def pre_filter(messages, state, host_identity_key, config):
    """Cheap filter before any per-message context is built: drop
    self-authored and already-processed messages.
    """
    ignore_self = config["loop_guard"]["ignore_self_authored_messages"]
    out = []
    for msg in messages:
        if ignore_self and identity_key(msg) == host_identity_key:
            continue
        if state.is_processed(msg["id"]):
            continue
        out.append(msg)
    return out


def thread_allows_reply(context, state, host_identity_key, config, now_ts):
    """Returns (allowed: bool, reason: str). Requires context already built
    (needs thread.recent_replies) since these rules are per-thread.
    """
    thread = context["thread"]
    cfg = config["loop_guard"]
    recent = thread["recent_replies"]

    host_replies = [m for m in recent if identity_key(m) == host_identity_key]
    if not host_replies:
        return True, "no prior host replies in thread"

    last_host_ts = max(m.get("ts", 0) for m in host_replies)
    external_after = [
        m for m in recent if identity_key(m) != host_identity_key and m.get("ts", 0) > last_host_ts
    ]

    max_allowed = cfg["max_host_replies_per_thread_window"]
    if len(host_replies) >= max_allowed:
        if cfg["require_external_new_message_to_reopen"] and not external_after:
            return (
                False,
                f"max_host_replies_per_thread_window ({max_allowed}) reached, no external reopen",
            )

    cooldown_minutes = cfg["cooldown_minutes"]
    minutes_since = (now_ts - last_host_ts) / 60000.0
    if minutes_since < cooldown_minutes and not external_after:
        return False, f"cooldown_minutes ({cooldown_minutes}) not elapsed, no external reopen"

    return True, "ok"
