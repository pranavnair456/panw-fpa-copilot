"""Thin Anthropic Claude wrapper shared by Stages 4-5 and the chat agent.

One interface for: structured extraction (`extract`, via the SDK's schema-
validated `messages.parse`) and free-form generation (`generate`). When no
ANTHROPIC_API_KEY is present the client reports `available == False`, and each
caller falls back to a deterministic offline path — so the whole project runs
(and is tested) with zero API cost, while the live Claude path activates the
moment a key is set.
"""
from __future__ import annotations
import os

try:
    import anthropic
    _SDK = True
except ImportError:  # pragma: no cover
    _SDK = False

from src import config

# Auto-load ANTHROPIC_API_KEY from THIS project's .env so it only needs to be set
# once (and never lives in shell history). We load the repo-root .env explicitly
# rather than searching up the tree, so an unrelated .env in a parent folder
# can't leak a stale key in. A real exported env var still wins (no override).
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=config.ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

_PLACEHOLDER = "sk-ant-your-key-here"  # the value shipped in .env.example


class LLMClient:
    def __init__(self):
        key = os.environ.get("ANTHROPIC_API_KEY")
        # Treat an empty or still-placeholder key as "no key" → offline mode,
        # rather than firing 401s against the API.
        self._key = key if (key and key != _PLACEHOLDER) else None
        self._client = anthropic.Anthropic() if (_SDK and self._key) else None

    @property
    def available(self) -> bool:
        return self._client is not None

    def extract(self, *, system: str, user: str, schema, model: str | None = None):
        """Schema-validated structured output. `schema` is a Pydantic model.

        Returns a validated instance of `schema`. Raises if no client (callers
        check `.available` first and use their offline fallback otherwise).
        """
        resp = self._client.messages.parse(
            model=model or config.EXTRACTION_MODEL,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        return resp.parsed_output

    def generate(self, *, system: str, user: str, model: str | None = None,
                 max_tokens: int = 4000) -> str:
        """Free-form text generation (Stage 5 brief, chat answers)."""
        resp = self._client.messages.create(
            model=model or config.SUMMARY_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")


# Module-level singleton for convenience.
client = LLMClient()
