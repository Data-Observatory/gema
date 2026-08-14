# llm/

LLM client abstraction — Protocol + middleware stack (Instructor → Retry → Cache).

## STRUCTURE

```
llm/
├── __init__.py
├── base.py             # LLMClient Protocol + LLMConfig (pydantic, extra="forbid")
├── factory.py          # create_llm_client() — middleware stack builder + provider cache
├── instructor_client.py# InstructorLLMClient — OpenAI + Instructor structured output
├── retry.py            # RetryableLLMClient — tenacity transport retry
└── (cache.py lives in parent — CachedLLMClient + CacheManager)
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Change retry rules | `retry.py` — see "Retry semantics" below |
| Add new OpenAI-compatible provider | Just config — no code. Add to `config/providers.yaml`. |
| Change temperature/max_tokens | Per-agent in `config/agents.yaml` |
| Inspect middleware order | `factory.py:create_llm_client()` |

## LLMClient Protocol (`base.py`)

```python
@runtime_checkable
class LLMClient(Protocol):
    model: str
    def complete(prompt, response_model, system_prompt=None, **kwargs) -> BaseModel
    def complete_raw(prompt, system_prompt=None, **kwargs) -> str
```

`LLMConfig` — `model`, `api_key: SecretStr`, `base_url`, `temperature=0.0`, `max_tokens=None`, `timeout=240.0`. `to_dict()` unwraps SecretStr.

## Middleware stack (`factory.py`)

Built bottom-up, wrapped by each layer:
1. `InstructorLLMClient(provider, model, ...)` — calls OpenAI + Instructor
2. `RetryableLLMClient(inner, ...)` — wraps with tenacity
3. `CachedLLMClient(inner, cache_dir)` — wraps with disk cache

**Module-global cache by composite key** (lines 19-22): identical provider+model+temp+seed+max_tokens+use_cache+use_retry → same client instance across calls.

## Retry semantics (`retry.py`) — CRITICAL

| Exception | Retryable? | Reason |
|-----------|------------|--------|
| `pydantic.ValidationError` | **NEVER** | Owned by Instructor layer |
| `InstructorRetryException` | **NEVER** | Owned by Instructor layer |
| `ValueError` | **NEVER** | Caller error, not transient |
| `APITimeoutError`, `APIConnectionError` | **ALWAYS** | Transport-level |
| `httpx.TimeoutException`, `httpx.ConnectError` | **ALWAYS** | Transport-level |
| HTTP 429 | **ALWAYS** | Rate limit (transient) |
| HTTP 5xx | Per-config | Server error |
| HTTP 4xx (non-429) | **NEVER** | Client error |

Dual import path for `InstructorRetryException` (instructor >=1.x vs <1.x) — `# type: ignore[no-redef]`, `# pragma: no cover` at lines 47-50.

Unreachable `RuntimeError` at line 138-139 exists solely for static type checkers.

## CONVENTIONS

- `max_tokens=None` → omit from API call (not passed as null). See `instructor_client.py:65-66`.
- API keys resolved from env var named in `ProviderConfig.api_key_env`.
- `temperature` defaults to 0.0 (deterministic) unless set per-agent.

## ANTI-PATTERNS

- **NEVER retry validation errors** — will loop forever on malformed LLM output.
- **NEVER instantiate `InstructorLLMClient` directly** — use `create_llm_client()` to get full stack + caching.
- **NEVER log API keys** — `SecretStr` exists for this reason. Use `.get_secret_value()` only when passing to client.

## NOTES

- Works with any OpenAI-compatible endpoint: OpenAI, OpenRouter, vLLM, Ollama, ZAI, OpenCode.
- Disk cache (`cache.py` in parent) lives outside this dir — SHA-256 keyed by prompt+model+response_model.
- `RetryableLLMClient` uses tenacity but configures custom `retry_if_exception_type` predicate.
