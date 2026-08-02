"""Model backend for Board Host: Google Vertex AI, pure REST (google-auth +
httpx only — no google-cloud-aiplatform / vertexai SDK dependency needed).

Routes by publisher:
  - anthropic  -> POST .../publishers/anthropic/models/{model}:rawPredict
  - google     -> POST .../publishers/google/models/{model}:generateContent

Primary model is tried first; on any failure (HTTP error, quota exhaustion,
network error) it falls back to the configured fallback model. As of
2026-08-02 Claude Sonnet 5 on this project is confirmed reachable but
quota-blocked (429 RESOURCE_EXHAUSTED) pending a manual GCP console
quota-increase request, so real traffic runs on the Gemini 3.1 Pro Preview
fallback until that's approved — no code change needed when it is, since
routing is automatic.
"""

import os

import google.auth
import httpx
from google.auth.transport.requests import Request


class VertexClientError(Exception):
    pass


class VertexClient:
    def __init__(self, project_id, credentials_path, primary, fallback, timeout_seconds=60):
        self.project_id = project_id
        self.primary = primary
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        if credentials_path:
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.abspath(credentials_path))
        self._credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

    def _token(self):
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return self._credentials.token

    def _headers(self):
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    def _call(self, cfg, system, messages, max_tokens):
        if cfg["publisher"] == "anthropic":
            return self._call_anthropic(cfg, system, messages, max_tokens)
        if cfg["publisher"] == "google":
            return self._call_gemini(cfg, system, messages, max_tokens)
        raise VertexClientError(f"unsupported publisher: {cfg['publisher']}")

    def _call_anthropic(self, cfg, system, messages, max_tokens):
        url = (
            f"https://aiplatform.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/{cfg['location']}/publishers/anthropic/models/{cfg['model']}:rawPredict"
        )
        payload = {
            "anthropic_version": "vertex-2023-10-16",
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system:
            payload["system"] = system
        resp = httpx.post(url, headers=self._headers(), json=payload, timeout=self.timeout_seconds)
        if resp.status_code != 200:
            raise VertexClientError(f"anthropic call failed: {resp.status_code} {resp.text[:500]}")
        data = resp.json()
        text = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        ).strip()
        if not text:
            raise VertexClientError(f"anthropic returned no text content: {data}")
        return text

    def _call_gemini(self, cfg, system, messages, max_tokens):
        url = (
            f"https://aiplatform.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/{cfg['location']}/publishers/google/models/{cfg['model']}:generateContent"
        )
        contents = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                # Ordinary social replies don't need extended thinking; keep
                # cost/latency low per docs/Board_Host_AI_v0.1.md §11, §20.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        resp = httpx.post(url, headers=self._headers(), json=payload, timeout=self.timeout_seconds)
        if resp.status_code != 200:
            raise VertexClientError(f"gemini call failed: {resp.status_code} {resp.text[:500]}")
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise VertexClientError(f"gemini returned no candidates: {data}")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            raise VertexClientError(f"gemini returned empty text: {data}")
        return text

    def generate(self, *, system, messages, max_tokens):
        """Returns (text, model_label). Tries primary, falls back on any error."""
        try:
            text = self._call(self.primary, system, messages, max_tokens)
            return text, f"{self.primary['publisher']}/{self.primary['model']}"
        except Exception as primary_error:
            try:
                text = self._call(self.fallback, system, messages, max_tokens)
                return (
                    text,
                    f"{self.fallback['publisher']}/{self.fallback['model']} "
                    f"(primary failed: {primary_error})",
                )
            except Exception as fallback_error:
                raise VertexClientError(
                    "both primary and fallback models failed. "
                    f"primary={primary_error!r} fallback={fallback_error!r}"
                ) from fallback_error
