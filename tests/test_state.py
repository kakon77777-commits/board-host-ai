import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.state import HostState


class TestHostState(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "host_state.json")

    def test_round_trip(self):
        state = HostState.load(self.path)
        state.advance_watermark(1000, "msg-1")
        state.mark_processed("msg-1")
        state.log_host_reply(ts=1000, topic="alpha", parent_id="msg-1", thread_root_id="msg-1")
        state.update_social_memory("eve/host/1", ts=1000, topic="alpha", reply_depth="L1")
        state.save()

        reloaded = HostState.load(self.path)
        self.assertEqual(reloaded.last_seen_timestamp, 1000)
        self.assertTrue(reloaded.is_processed("msg-1"))
        self.assertEqual(reloaded.topic_visits()["alpha"]["visit_count"], 1)
        mem = reloaded.get_social_memory("eve/host/1")
        self.assertEqual(mem["last_interaction"], 1000)
        self.assertIn("alpha", mem["recent_topics"])

    def test_mark_processed_respects_cap(self):
        state = HostState.load(self.path)
        for i in range(10):
            state.mark_processed(f"msg-{i}", keep_max=5)
        ids = state._data["processed_message_ids"]
        self.assertEqual(len(ids), 5)
        self.assertEqual(ids[-1], "msg-9")

    def test_advance_watermark_never_regresses(self):
        state = HostState.load(self.path)
        state.advance_watermark(5000, "a")
        state.advance_watermark(3000, "b")
        self.assertEqual(state.last_seen_timestamp, 5000)


if __name__ == "__main__":
    unittest.main()
