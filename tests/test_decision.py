import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.state import HostState
from src.decision import decide, score_candidate

BASE_CONFIG = {
    "board_host": {
        "scan_interval_minutes": 15,
        "social": {"same_author_cooldown_minutes": 60},
    },
    "topic_diversity": {
        "enabled": True,
        "hot_topic_reply_penalty": 0.18,
        "hot_topic_window_replies": 3,
        "cold_topic_bonus": 0.12,
        "cold_topic_min_runs_since_visit": 2,
    },
}


def make_context(content, msg_type="comment", topic="general", participant_count=1, already_replied_by_host=False):
    return {
        "message": {"id": "m1", "author": "someone", "topic": topic, "type": msg_type, "content": content, "timestamp": 1000},
        "thread": {
            "root_id": "m1",
            "recent_replies": [],
            "participant_count": participant_count,
            "already_replied_by_host": already_replied_by_host,
        },
        "author_context": {"social_memory": {"last_interaction": None, "recent_topics": [], "preferred_language": None, "recent_reply_depth": 0}},
        "board_context": {"topic_stats": None, "all_topics": []},
    }


class TestDecide(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state = HostState.load(os.path.join(self.tmpdir, "state.json"))

    def test_low_signal_skips(self):
        ctx = make_context("ok", participant_count=5)
        decision = decide(ctx, self.state, BASE_CONFIG, now_ts=100000)
        self.assertEqual(decision["action"], "skip")

    def test_question_in_reply_starved_thread_gets_reply(self):
        ctx = make_context(
            "Here's a question worth extending: what happens if the invariant breaks under concurrent writes?",
            participant_count=1,
        )
        decision = decide(ctx, self.state, BASE_CONFIG, now_ts=100000)
        self.assertEqual(decision["action"], "reply")

    def test_already_replied_by_host_suppresses_score(self):
        ctx_normal = make_context("Interesting question: why does this fail?", participant_count=1)
        ctx_loop = make_context("Interesting question: why does this fail?", participant_count=1, already_replied_by_host=True)
        score_normal = score_candidate(ctx_normal, self.state, BASE_CONFIG, now_ts=100000)
        score_loop = score_candidate(ctx_loop, self.state, BASE_CONFIG, now_ts=100000)
        self.assertLess(score_loop, score_normal)

    def test_deep_tier_requires_type_length_and_keyword(self):
        long_content = "why does this happen? " + ("research detail. " * 40)
        ctx = make_context(long_content, msg_type="objection", topic="deep-topic")
        decision = decide(ctx, self.state, BASE_CONFIG, now_ts=100000)
        if decision["action"] == "reply":
            self.assertIn(decision["length_tier"], ("L2", "L3"))

    def test_hot_topic_penalty_lowers_score(self):
        ctx = make_context("A real question: what do you think about this?", topic="hot-topic")
        self.state.log_host_reply(ts=1, topic="hot-topic", parent_id="p1", thread_root_id="p1")
        self.state.log_host_reply(ts=2, topic="hot-topic", parent_id="p2", thread_root_id="p2")
        score_with_penalty = score_candidate(ctx, self.state, BASE_CONFIG, now_ts=1000)

        fresh_state = HostState.load(os.path.join(self.tmpdir, "fresh.json"))
        score_without_penalty = score_candidate(ctx, fresh_state, BASE_CONFIG, now_ts=1000)

        self.assertLess(score_with_penalty, score_without_penalty)

    def test_cold_topic_bonus_raises_score(self):
        ctx_cold = make_context("A real question: what do you think about this?", topic="never-visited")
        ctx_visited = make_context("A real question: what do you think about this?", topic="just-visited")
        self.state.log_host_reply(ts=999999, topic="just-visited", parent_id="p1", thread_root_id="p1")

        score_cold = score_candidate(ctx_cold, self.state, BASE_CONFIG, now_ts=1000000)
        score_visited = score_candidate(ctx_visited, self.state, BASE_CONFIG, now_ts=1000000)
        self.assertGreater(score_cold, score_visited)


if __name__ == "__main__":
    unittest.main()
