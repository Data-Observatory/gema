# llm/

LLM client abstraction: Protocol + middleware stack ((Instructor | Responses) → Retry → Cache).

## STRUCTURE

```
llm/
├── __init__.py
├── base.py               # LLMClient Protocol + LLMConfig (pydantic, extra="forbid")
├── factory.py            # create_llm_client(): middleware stack builder + module-global client cache
├── instructor_client.py  # InstructorLLMClient: OpenAI Chat Completions + Instructor structured output (+ tool-call loop)
├── responses_client.py   # ResponsesLLMClient: OpenAI Responses API, native json_schema output, hand-rolled reask (+ tool loop)
├── tools.py              # TOOL_REGISTRY (currently: lookup_organization -> ROR), tool_schemas(), execute_tool()
├── retry.py              # RetryableLLMClient: tenacity transport retry
└── (cache.py lives in parent — CachedLLMClient + CacheManager)
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Change retry rules | `retry.py` (see "Retry semantics" below) |
| Add new OpenAI-compatible provider | Config only, no code. Add an entry to `config/agents.yaml`'s inline `providers:` block (the runtime list). `config/providers.yaml` is only Visor's autofill preset pool / `gema list-known-providers`; the pipeline never reads it |
| Route a model to the Responses API | `api_style: responses` on the provider or a `model_overrides` entry (`config/models.py`) |
| Add a tool an agent can call | `tools.py` `TOOL_REGISTRY` (schema + executor), then list it in that agent's `tools:` |
| Change temperature/max_tokens/reasoning_effort | Per-agent in `config/agents.yaml` |
| Inspect middleware order | `factory.py:create_llm_client()` |

## LLMClient Protocol (`base.py`)

```python
@runtime_checkable
class LLMClient(Protocol):
    @property
    def model(self) -> str: ...
    def complete(prompt, response_model, system_prompt=None, **kwargs) -> BaseModel
    def complete_raw(prompt, system_prompt=None, **kwargs) -> str
```

`complete_with_usage()` / `complete_with_tools()` are optional, duck-typed extensions that
the real production chain (both clients, Retryable, Cached) implements, so test mocks don't
need them. `agents/base.py` looks them up with `getattr(..., None)`.

`LLMConfig`: `model`, `api_key: SecretStr`, `base_url`, `temperature=0.0`, `seed`,
`max_tokens=None`, `timeout=240.0`, `extra_body`, `session_header`, `api_style`,
`reasoning_effort`.

## Middleware stack (`factory.py`)

Built bottom-up, wrapped by each layer:
1. `InstructorLLMClient(config)`, or `ResponsesLLMClient(config)` when
   `provider.effective_api_style(model) == "responses"`
2. `RetryableLLMClient(inner)`: wraps with tenacity (if `use_retry`)
3. `CachedLLMClient(inner, cache_manager)`: wraps with disk cache (if `use_cache`)

**Module-global client cache by composite key** (`factory.py:110-129`):
provider+model+temperature+seed+max_tokens+use_cache+use_retry+extra_body, plus
`api_style`/`reasoning_effort` only for a non-default api_style, plus an API-key fingerprint
only when an explicit `api_key=` is passed (Visor's per-session keys). Identical parameters
return the same client instance. `reset_client_cache()` drops instances (e.g. after a key
change); `clear_response_cache()` empties the on-disk response cache.

## Retry semantics (`retry.py`, `_is_retryable`): CRITICAL

| Exception | Retryable? | Reason |
|-----------|------------|--------|
| `pydantic.ValidationError` | **NEVER** | Owned by Instructor layer |
| `ValueError` | **NEVER** | Caller error, not transient |
| `InstructorRetryException` | **Only if its `__cause__` is retryable** | Instructor raises it both for permanent validation dead-ends and for transport errors (e.g. sustained 429) that exhausted its own internal retries; unwrapped and re-checked against the root cause |
| `APITimeoutError`, `APIConnectionError` | **ALWAYS** | Transport-level |
| `httpx.TimeoutException`, `httpx.ConnectError` | **ALWAYS** | Transport-level |
| HTTP 429 (`RateLimitError`) | **ALWAYS** | Rate limit (transient) |
| HTTP 5xx | Per-config (`RetryConfig.retry_on_status`, default 500/502/503/504) | Server error |
| HTTP 4xx (non-429) | **NEVER** | Client error |

`RetryConfig` defaults: `max_retries=6`, exponential backoff (`initial_wait=1.0`,
`max_wait=60.0`) plus jitter. The predicate is passed to tenacity via
`retry_if_exception(lambda exc: _is_retryable(...))`. A retry re-runs the whole call,
including a whole tool-call loop.

Dual import path for `InstructorRetryException` (`instructor.core` vs.
`instructor.exceptions`), guarded by `# pragma: no cover`.

## CONVENTIONS

- `max_tokens=None` → omitted from the API call (not passed as null).
- API keys resolved from the env var named in `ProviderConfig.api_key_env`, unless an explicit `api_key=` is passed to `create_llm_client()`.
- `temperature` defaults to 0.0 (deterministic) unless set per-agent.
- `seed` is sent via `extra_body={"seed": ...}`.
- `session_header` (e.g. `x-opencode-session`) gets a fresh random ID per conversation (one `complete*()` call). Never part of any cache key.

## ANTI-PATTERNS

- **NEVER retry validation errors.** Doing so loops forever on malformed LLM output.
- **NEVER instantiate `InstructorLLMClient`/`ResponsesLLMClient` directly.** Use `create_llm_client()` to get the full stack + caching.
- **NEVER log API keys.** That's why `SecretStr` exists. Use `.get_secret_value()` only when passing to the client.

## NOTES

- Works with any OpenAI-compatible endpoint: OpenAI, OpenRouter, vLLM, Ollama, ZAI, OpenCode.
- The disk response cache (`cache.py` in the parent) lives outside this dir: SHA-256 over prompt+model+response_model+temperature+seed, plus extra_body/tools/api_style+reasoning_effort only when set. Provider is not in the key.
