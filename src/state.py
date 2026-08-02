"""Host state persistence: last-seen watermark, processed-id ledger,
host reply log (for loop_guard + topic diversity), and small per-agent
social memory. See docs/Board_Host_AI_v0.1.md §6, §12, §14.
"""

import json
import os


def _default_state():
    return {
        "last_seen_timestamp": 0,
        "last_seen_message_id": None,
        "processed_message_ids": [],
        "host_reply_log": [],
        "social_memory": {},
        "topic_visits": {},
        "proactive_nudges": [],
    }


class HostState:
    def __init__(self, path):
        self.path = path
        self._data = _default_state()

    @classmethod
    def load(cls, path):
        state = cls(path)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            state._data = {**_default_state(), **loaded}
        return state

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)

    @property
    def last_seen_timestamp(self):
        return self._data["last_seen_timestamp"]

    def advance_watermark(self, ts, message_id):
        if ts > self._data["last_seen_timestamp"]:
            self._data["last_seen_timestamp"] = ts
            self._data["last_seen_message_id"] = message_id

    def is_processed(self, message_id):
        return message_id in self._data["processed_message_ids"]

    def mark_processed(self, message_id, keep_max=2000):
        ids = self._data["processed_message_ids"]
        if message_id not in ids:
            ids.append(message_id)
            if len(ids) > keep_max:
                del ids[: len(ids) - keep_max]

    def log_host_reply(self, *, ts, topic, parent_id, thread_root_id, keep_max=500):
        log = self._data["host_reply_log"]
        log.append(
            {
                "ts": ts,
                "topic": topic,
                "parent_id": parent_id,
                "thread_root_id": thread_root_id,
            }
        )
        if len(log) > keep_max:
            del log[: len(log) - keep_max]
        self._data["topic_visits"][topic or ""] = {
            "last_visit_ts": ts,
            "visit_count": self._data["topic_visits"].get(topic or "", {}).get("visit_count", 0) + 1,
        }

    def host_reply_log(self):
        return list(self._data["host_reply_log"])

    def topic_visits(self):
        return dict(self._data["topic_visits"])

    def record_proactive_nudge(self, *, ts, topic):
        nudges = self._data["proactive_nudges"]
        nudges.append({"ts": ts, "topic": topic})
        if len(nudges) > 200:
            del nudges[: len(nudges) - 200]

    def proactive_nudges(self):
        return list(self._data["proactive_nudges"])

    def get_social_memory(self, agent_key):
        return self._data["social_memory"].get(
            agent_key,
            {
                "last_interaction": None,
                "recent_topics": [],
                "preferred_language": None,
                "recent_reply_depth": 0,
            },
        )

    def update_social_memory(self, agent_key, *, ts, topic, reply_depth):
        mem = self.get_social_memory(agent_key)
        mem["last_interaction"] = ts
        if topic:
            recent = [t for t in mem["recent_topics"] if t != topic]
            recent.insert(0, topic)
            mem["recent_topics"] = recent[:10]
        mem["recent_reply_depth"] = reply_depth
        self._data["social_memory"][agent_key] = mem
