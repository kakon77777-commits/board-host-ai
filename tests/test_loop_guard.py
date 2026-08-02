import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.state import HostState
from src.loop_guard import pre_filter, thread_allows_reply

HOST_IDENTITY = {"eigenself": "evemisslab/board-host", "slice": "AI Board Resident Host", "instance": "persistent-host-v0.1"}
HOST_KEY = "evemisslab/board-host/AI Board Resident Host/persistent-host-v0.1"

BASE_CONFIG = {
    "loop_guard": {
        "ignore_self_authored_messages": True,
        "max_host_replies_per_thread_window": 2,
        "require_external_new_message_to_reopen": True,
        "cooldown_minutes": 30,
    }
}


def host_msg(id_, ts):
    return {"id": id_, "ts": ts, **HOST_IDENTITY}


def external_msg(id_, ts, name="other-ai"):
    return {"id": id_, "ts": ts, "eigenself": name, "slice": "s", "instance": "i"}


class TestPreFilter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state = HostState.load(os.path.join(self.tmpdir, "state.json"))

    def test_drops_self_authored(self):
        messages = [host_msg("h1", 100), external_msg("e1", 200)]
        out = pre_filter(messages, self.state, HOST_KEY, BASE_CONFIG)
        self.assertEqual([m["id"] for m in out], ["e1"])

    def test_drops_already_processed(self):
        self.state.mark_processed("e1")
        messages = [external_msg("e1", 100), external_msg("e2", 200)]
        out = pre_filter(messages, self.state, HOST_KEY, BASE_CONFIG)
        self.assertEqual([m["id"] for m in out], ["e2"])


class TestThreadAllowsReply(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state = HostState.load(os.path.join(self.tmpdir, "state.json"))

    def _context(self, recent_replies):
        return {"thread": {"recent_replies": recent_replies, "root_id": "root", "participant_count": 2, "already_replied_by_host": True}}

    def test_allows_when_no_prior_host_reply(self):
        ctx = self._context([external_msg("e1", 100)])
        allowed, _ = thread_allows_reply(ctx, self.state, HOST_KEY, BASE_CONFIG, now_ts=100000)
        self.assertTrue(allowed)

    def test_blocks_after_max_replies_without_reopen(self):
        recent = [external_msg("e1", 100), host_msg("h1", 200), host_msg("h2", 300)]
        ctx = self._context(recent)
        allowed, reason = thread_allows_reply(ctx, self.state, HOST_KEY, BASE_CONFIG, now_ts=400)
        self.assertFalse(allowed)
        self.assertIn("max_host_replies_per_thread_window", reason)

    def test_allows_after_external_reopen(self):
        recent = [
            external_msg("e1", 100),
            host_msg("h1", 200),
            host_msg("h2", 300),
            external_msg("e2", 400),
        ]
        ctx = self._context(recent)
        allowed, _ = thread_allows_reply(ctx, self.state, HOST_KEY, BASE_CONFIG, now_ts=500)
        self.assertTrue(allowed)

    def test_cooldown_blocks_immediate_re_reply(self):
        recent = [external_msg("e1", 100), host_msg("h1", 200)]
        ctx = self._context(recent)
        now_ts = 200 + 5 * 60000  # 5 minutes later, cooldown is 30
        allowed, reason = thread_allows_reply(ctx, self.state, HOST_KEY, BASE_CONFIG, now_ts=now_ts)
        self.assertFalse(allowed)
        self.assertIn("cooldown_minutes", reason)

    def test_cooldown_elapsed_allows_reply(self):
        recent = [external_msg("e1", 100), host_msg("h1", 200)]
        ctx = self._context(recent)
        now_ts = 200 + 31 * 60000  # 31 minutes later
        allowed, _ = thread_allows_reply(ctx, self.state, HOST_KEY, BASE_CONFIG, now_ts=now_ts)
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
