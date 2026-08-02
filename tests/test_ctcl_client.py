import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.ctcl_client import safe_register, CtclClientError


class _RaisingClient:
    def register_instant(self, label=None):
        raise CtclClientError("simulated CTCL outage")


class _WorkingClient:
    def __init__(self):
        self.calls = []

    def register_instant(self, label=None):
        self.calls.append(label)
        return f"ctcl:instant:fake-{len(self.calls)}"


class TestSafeRegister(unittest.TestCase):
    def test_none_client_returns_none(self):
        self.assertIsNone(safe_register(None, "some-label"))

    def test_failure_degrades_to_none_without_raising(self):
        logs = []
        result = safe_register(_RaisingClient(), "some-label", log=logs.append)
        self.assertIsNone(result)
        self.assertTrue(any("non-fatal" in line for line in logs))

    def test_success_returns_id_and_passes_label(self):
        client = _WorkingClient()
        result = safe_register(client, "board-host:observed:msg-1")
        self.assertEqual(result, "ctcl:instant:fake-1")
        self.assertEqual(client.calls, ["board-host:observed:msg-1"])


if __name__ == "__main__":
    unittest.main()
