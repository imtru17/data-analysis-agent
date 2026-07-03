import time

import anthropic as _sdk


class AnthropicProvider:
    DEFAULT_MODEL = "claude-sonnet-4-6"

    # Bounded exponential backoff for transient errors (429 rate-limit, 5xx).
    # Production resilience — not a test stub; real calls hit real transient
    # errors (e.g. an org-level rate limit) and must recover, not fail the run.
    _MAX_ATTEMPTS = 5
    _BASE_DELAY_S = 2.0

    def __init__(self, api_key: str, model: str) -> None:
        self._client = _sdk.Anthropic(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        text, _usage = self.call_with_usage(prompt, system=system)
        return text

    def call_with_usage(
        self, prompt: str, *, system: str | None = None
    ) -> tuple[str, dict]:
        """Return (text, {"prompt_tokens", "completion_tokens"}) from the real
        Anthropic response usage. Retries 429/5xx with bounded exponential
        backoff; other errors propagate immediately."""
        kwargs: dict = dict(
            model=self._model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system

        last_exc: Exception | None = None
        for attempt in range(self._MAX_ATTEMPTS):
            try:
                msg = self._client.messages.create(**kwargs)
                break
            except (_sdk.RateLimitError, _sdk.InternalServerError, _sdk.APIConnectionError) as exc:
                last_exc = exc
                if attempt == self._MAX_ATTEMPTS - 1:
                    raise
                delay = self._retry_after(exc) or self._BASE_DELAY_S * (2**attempt)
                time.sleep(delay)
        else:  # pragma: no cover — loop always breaks or raises
            raise last_exc  # type: ignore[misc]

        text = "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        )
        usage = getattr(msg, "usage", None)
        usage_dict = {
            "prompt_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        }
        return text, usage_dict

    @staticmethod
    def _retry_after(exc: Exception) -> float | None:
        """Honour a server-provided Retry-After header when present."""
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if not headers:
            return None
        value = headers.get("retry-after")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
