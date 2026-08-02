"""Thin REST client for CTCL (共同時間座標層 / Common Temporal Coordinate
Layer), commoninstant.org. Stdlib-only (urllib), same pattern as
board_client.py.

Board Host registers verified instants for its own interactions per
docs/Board_Host_AI_v0.1.md §15.2's temporal metadata schema
(event/write/observed/reply instants). CTCL is an enrichment layer, not
a hard dependency — §15.1 is explicit that v0.1 does not depend on it —
so `safe_register` is the only entry point watcher.py should use: any
CTCL failure degrades to a missing field, never a blocked reply.
"""

import json
import urllib.error
import urllib.request


class CtclClientError(Exception):
    pass


class CtclClient:
    def __init__(self, base_url, timeout_seconds=10, user_agent="board-host-ai/0.1"):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def _get_json(self, url):
        req = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        return self._send(req)

    def _post_json(self, url, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
            method="POST",
        )
        return self._send(req)

    def _send(self, req):
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            raise CtclClientError(f"CTCL request failed: {e}") from e
        if not body.get("ok"):
            raise CtclClientError(f"CTCL returned non-ok response: {body}")
        return body["data"]

    def register_instant(self, label=None):
        payload = {"label": label} if label else {}
        data = self._post_json(self.base_url + "/v1/instants", payload)
        return data["id"]

    def get_instant(self, instant_id):
        return self._get_json(f"{self.base_url}/v1/instant/{instant_id}")


def safe_register(client, label, log=print):
    """Never raises. Returns the instant id, or None if CTCL is
    unreachable/disabled — callers must treat None as "no CTCL
    provenance for this field," not as an error to react to.
    """
    if client is None:
        return None
    try:
        return client.register_instant(label=label)
    except CtclClientError as e:
        log(f"[ctcl] registration failed (non-fatal, continuing without it): {e}")
        return None
