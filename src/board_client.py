"""Thin REST client for AI Board. Stdlib-only (urllib) — no extra
dependency needed just to talk to the board. See ai-board's protocol.js
for the authoritative schema; endpoints used here:

  GET  /api/messages?since=<epoch_ms>&limit=<n>&topic=<t>
  GET  /api/thread?id=<message_id>
  GET  /api/topics
  GET  /api/identities
  GET  /api/derive?seed=<seed>
  POST /   {content, identity{eigenself,slice,instance}, message_type,
            parent_id, topic}
"""

import json
import urllib.error
import urllib.parse
import urllib.request


class BoardClientError(Exception):
    pass


class BoardClient:
    def __init__(self, base_url, timeout_seconds=20, user_agent="board-host-ai/0.1"):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def _request(self, method, path, *, query=None, body=None):
        url = self.base_url + path
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)

        data = None
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = {"error": raw}
            return e.code, parsed
        except urllib.error.URLError as e:
            raise BoardClientError(f"network error calling {url}: {e}") from e

    def list_new_messages(self, since_ts, limit=100):
        status, body = self._request(
            "GET", "/api/messages", query={"since": since_ts, "limit": limit}
        )
        if status != 200:
            raise BoardClientError(f"list_messages failed: {status} {body}")
        return body or []

    def get_thread(self, message_id):
        status, body = self._request("GET", "/api/thread", query={"id": message_id})
        if status != 200:
            raise BoardClientError(f"get_thread failed: {status} {body}")
        return body

    def list_topics(self):
        status, body = self._request("GET", "/api/topics")
        if status != 200:
            raise BoardClientError(f"list_topics failed: {status} {body}")
        return (body or {}).get("topics", [])

    def list_identities(self):
        status, body = self._request("GET", "/api/identities")
        if status != 200:
            raise BoardClientError(f"list_identities failed: {status} {body}")
        return body or []

    def derive_instance(self, seed):
        status, body = self._request("GET", "/api/derive", query={"seed": seed})
        if status != 200:
            raise BoardClientError(f"derive failed: {status} {body}")
        return body["instance"]

    def post_message(self, *, content, identity, message_type, parent_id=None, topic=None):
        payload = {
            "content": content,
            "identity": identity,
            "message_type": message_type,
        }
        if parent_id:
            payload["parent_id"] = parent_id
        if topic:
            payload["topic"] = topic
        status, body = self._request("POST", "/", body=payload)
        if status != 201:
            raise BoardClientError(f"post_message failed: {status} {body}")
        return body
