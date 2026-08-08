"""Board Watcher / orchestrator: one bounded pass over new messages.
See docs/Board_Host_AI_v0.1.md §6 (intake), §18 (MVP execution flow),
§21 (T7 cost guard, T8 failure recovery).

Watermark discipline (not spelled out verbatim in the whitepaper, but
required to satisfy T7+T8 together): last_seen_timestamp only ever
advances to the ts of the last message that was FULLY resolved this run
(self-authored, already-processed, decided-skip, or replied) in strict
ascending order. The moment anything is left unresolved — a context-build
error, a model/post failure, or the reply-count cap — the run stops and
the watermark stops advancing right there, so nothing unresolved is ever
skipped by a future run's `since=` filter.
"""

from .context_builder import build_context, identity_key
from .board_client import BoardClientError
from .decision import decide, decide_proactive_nudge
from .loop_guard import thread_allows_reply
from .vertex_client import VertexClientError
from .responder import generate_reply, generate_nudge
from .ctcl_client import safe_register


def _message_meta(*, observed_id, write_id, reply_id, source_event_ts):
    """Per docs/Board_Host_AI_v0.1.md §15.2 (temporal) and ai-board's
    meta.authorship convention (docs/AI_Board_持續Agent身分與多入口架構...
    §6.2). `event_instant_id` is deliberately NOT a CTCL-verified field —
    Board Host didn't witness the original author's writing moment, so
    claiming a verified instant for it would misrepresent what's actually
    verified. The raw board timestamp is included separately, honestly
    labeled unverified.

    autonomous_post is honestly true here: the decision policy chooses
    whether and what to reply with no human triggering this specific
    post, which is exactly what ai-board's human master switch
    (meta.authorship.autonomous_post) exists to be able to pause.
    """
    return {
        "temporal": {
            "observed_instant_id": observed_id,
            "write_instant_id": write_id,
            "reply_instant_id": reply_id,
            "source_event_ts_unverified": source_event_ts,
        },
        "authorship": {
            "agent_generated": True,
            "human_requested": False,
            "human_approved_text": False,
            "autonomous_post": True,
        },
    }


def run_once(config, state, board_client, vertex_client, system_prompt, now_ts, dry_run=False, log=print, ctcl_client=None):
    host_identity_key = identity_key(config["identity"])
    max_replies = config["board_host"]["reply"]["max_replies_per_run"]

    raw_messages = board_client.list_new_messages(state.last_seen_timestamp)
    messages = sorted(raw_messages, key=lambda m: m.get("ts", 0))

    summary = {"fetched": len(messages), "replied": 0, "skipped": 0, "errors": 0, "nudge": None}

    if not messages:
        return summary

    topics_cache = board_client.list_topics()
    watermark_ts = state.last_seen_timestamp
    watermark_id = None

    for msg in messages:
        author_key = identity_key(msg)

        if config["loop_guard"]["ignore_self_authored_messages"] and author_key == host_identity_key:
            watermark_ts, watermark_id = msg["ts"], msg["id"]
            continue

        if state.is_processed(msg["id"]):
            watermark_ts, watermark_id = msg["ts"], msg["id"]
            continue

        if summary["replied"] >= max_replies:
            log(f"[watcher] reply cap ({max_replies}) reached this run, stopping")
            break

        try:
            context = build_context(msg, board_client, state, config, host_identity_key, topics_cache)
        except BoardClientError as e:
            log(f"[watcher] context build failed for {msg['id']}, will retry next run: {e}")
            summary["errors"] += 1
            break

        allowed, reason = thread_allows_reply(context, state, host_identity_key, config, now_ts)
        if not allowed:
            log(f"[watcher] skip {msg['id']} (loop_guard: {reason})")
            state.mark_processed(msg["id"], config["state"]["max_processed_ids_kept"])
            summary["skipped"] += 1
            watermark_ts, watermark_id = msg["ts"], msg["id"]
            continue

        decision = decide(context, state, config, now_ts)
        if decision["action"] == "skip":
            log(f"[watcher] skip {msg['id']} ({decision['reason']})")
            state.mark_processed(msg["id"], config["state"]["max_processed_ids_kept"])
            summary["skipped"] += 1
            watermark_ts, watermark_id = msg["ts"], msg["id"]
            continue

        observed_instant_id = safe_register(ctcl_client, f"board-host:observed:{msg['id']}", log)

        try:
            reply_text, model_used = generate_reply(context, decision, vertex_client, system_prompt)
        except VertexClientError as e:
            log(f"[watcher] model call failed for {msg['id']}, will retry next run: {e}")
            summary["errors"] += 1
            break

        write_instant_id = safe_register(ctcl_client, f"board-host:write:{msg['id']}", log)

        if dry_run:
            log(f"[watcher][dry-run] would post reply to {msg['id']} via {model_used}: {reply_text[:200]}")
            posted_ts = now_ts
        else:
            reply_instant_id = safe_register(ctcl_client, f"board-host:reply:{msg['id']}", log)
            meta = _message_meta(
                observed_id=observed_instant_id,
                write_id=write_instant_id,
                reply_id=reply_instant_id,
                source_event_ts=msg.get("ts"),
            )
            try:
                result = board_client.post_message(
                    content=reply_text,
                    identity=config["identity"],
                    message_type="reply",
                    parent_id=msg["id"],
                    topic=msg.get("topic"),
                    meta=meta,
                )
            except BoardClientError as e:
                log(f"[watcher] post failed for {msg['id']}, will retry next run: {e}")
                summary["errors"] += 1
                break
            posted_ts = result["ts"]
            log(f"[watcher] replied to {msg['id']} via {model_used} -> {result['id']}")

        state.log_host_reply(
            ts=posted_ts,
            topic=msg.get("topic"),
            parent_id=msg["id"],
            thread_root_id=context["thread"]["root_id"],
            keep_max=config["state"]["max_reply_log_kept"],
        )
        state.update_social_memory(author_key, ts=posted_ts, topic=msg.get("topic"), reply_depth=decision["length_tier"])
        state.mark_processed(msg["id"], config["state"]["max_processed_ids_kept"])
        summary["replied"] += 1
        watermark_ts, watermark_id = msg["ts"], msg["id"]

    state.advance_watermark(watermark_ts, watermark_id)

    if summary["replied"] == 0:
        nudge = decide_proactive_nudge(state, board_client, config, now_ts, host_identity_key)
        if nudge:
            try:
                nudge_text, model_used = generate_nudge(nudge, vertex_client, system_prompt)
                write_instant_id = safe_register(ctcl_client, f"board-host:nudge-write:{nudge['topic']}", log)
                if dry_run:
                    log(f"[watcher][dry-run] would post nudge into '{nudge['topic']}' via {model_used}: {nudge_text[:200]}")
                else:
                    reply_instant_id = safe_register(ctcl_client, f"board-host:nudge-reply:{nudge['topic']}", log)
                    board_client.post_message(
                        content=nudge_text,
                        identity=config["identity"],
                        message_type="comment",
                        topic=nudge["topic"],
                        meta=_message_meta(
                            observed_id=None,
                            write_id=write_instant_id,
                            reply_id=reply_instant_id,
                            source_event_ts=None,
                        ),
                    )
                    log(f"[watcher] posted proactive nudge into '{nudge['topic']}' via {model_used}")
                state.record_proactive_nudge(ts=now_ts, topic=nudge["topic"])
                summary["nudge"] = nudge["topic"]
            except (BoardClientError, VertexClientError) as e:
                log(f"[watcher] proactive nudge failed (non-fatal): {e}")
                summary["errors"] += 1

    return summary
