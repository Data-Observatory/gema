"""Responses-API-backed LLM client implementing LLMClient Protocol.

A sibling of InstructorLLMClient (llm/instructor_client.py) -- NOT a
subclass. The two share almost no body: different request shape (``input=``
vs ``messages=``), different response shape (``output_text``/``output`` vs
``choices[0].message``), a different structured-output mechanism (native
``text.format={"type":"json_schema",...}`` vs Instructor's function-calling
machinery), and different usage field names (``input_tokens``/
``output_tokens`` vs ``prompt_tokens``/``completion_tokens``).

Exists for models that reject Chat Completions outright. Confirmed
2026-09-06 against opencode:muse-spark-1.3-contributor: real HTTP 500 from
Chat Completions, HTTP 200 from the Responses API, same key/model -- see
config/models.py's ``ApiStyle`` docstring. A dozen manual probe calls against
that same model informed every design choice below (recorded in this
branch's task brief); notable ones inlined as comments at the relevant line.

instructor's reask machinery is tool-choice-specific and doesn't apply to
this wire format, so structured-output validation + reask is hand-rolled
here in ``_complete_structured`` rather than delegated.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from openai import OpenAI
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, ValidationError

from metadata_enricher.llm.base import LLMConfig
from metadata_enricher.llm.tools import execute_tool, tool_schemas
from metadata_enricher.types import TokenUsage

logger = logging.getLogger(__name__)

# extra_body keys that are valid on Chat Completions but produce a hard 400
# ("unknown parameter ...") on the Responses API. Probed 2026-09-06:
# extra_body={"seed": 42} -> 400 "unknown parameter 'seed'";
# extra_body={"thinking": {"type": "disabled"}} -> 400 "unknown parameter
# 'thinking'". Never forward either on this path.
_UNSUPPORTED_ON_RESPONSES: tuple[str, ...] = ("seed", "thinking")

# Cap on how many formatted validation-error lines get sent back to the
# model in a reask turn -- keeps a real-payload ValidationError (which can
# carry dozens of per-field errors) from ballooning the reask prompt.
_MAX_VALIDATION_ERROR_LINES = 20


def _build_responses_extra_body(config: LLMConfig) -> dict[str, Any] | None:
    """Reshape ``config.extra_body`` for the Responses API.

    Deliberately does NOT reuse instructor_client._build_extra_body -- that
    helper's whole job is injecting ``seed`` into extra_body, which is
    exactly the 400 this path must avoid. ``config.seed`` is handled
    separately (one warning at construction time, see
    ResponsesLLMClient.__init__) and is never forwarded from here either;
    this function only drops disallowed keys that arrived via
    ``config.extra_body`` itself.
    """
    if not config.extra_body:
        return None
    extra_body = dict(config.extra_body)
    for key in _UNSUPPORTED_ON_RESPONSES:
        if key in extra_body:
            del extra_body[key]
            logger.warning(
                "extra_body key %r is not supported on the Responses API "
                "(probed 2026-09-06: HTTP 400 'unknown parameter'); dropped "
                "for model=%r.",
                key,
                config.model,
            )
    return extra_body or None


def _build_extra_headers(config: LLMConfig) -> dict[str, str] | None:
    """Fresh per-conversation header (see LLMConfig.session_header's
    docstring / instructor_client._build_extra_headers, whose contract this
    mirrors exactly). Must be called once per complete()/complete_with_usage()
    /complete_with_tools()/complete_raw() invocation and its result reused
    across that call's own retries/tool-loop rounds -- never memoized or
    reused across separate calls, and never fed into cache.py's key.

    Duplicated rather than imported from instructor_client on purpose --
    this module is a sibling, not a subclass (see module docstring)."""
    if not config.session_header:
        return None
    return {config.session_header: f"gema-{uuid.uuid4().hex}"}


def _text_format(response_model: type[BaseModel]) -> dict[str, Any]:
    """Build the ``text=`` request param for native json_schema structured
    output. Must go through ``to_strict_json_schema`` -- a raw
    ``response_model.model_json_schema()`` fails with a 400 requiring
    ``additionalProperties: false`` (probed 2026-09-06); ``strict: False``
    instead returns 200 but silently corrupts data (the model free-forms a
    wrong key name and pydantic silently drops it, no error surfaces
    anywhere), so ``strict`` must always be ``True``, never a config knob.
    """
    return {
        "format": {
            "type": "json_schema",
            "name": response_model.__name__,
            "schema": to_strict_json_schema(response_model),
            "strict": True,
        }
    }


def _extract_json(text: str) -> str:
    """Best-effort tolerance for near-JSON model output: return as-is if it
    already looks like a JSON object, else strip a ```json fence, else slice
    from the first ``{`` to the last ``}``. Never raises -- an unparseable
    string is returned unchanged so the caller's own JSON decode surfaces
    the real error."""
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]  # drop the opening ``` or ```json fence line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
        if candidate:
            return candidate
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and last > first:
        return stripped[first : last + 1]
    return stripped


def _format_validation_error(exc: ValidationError) -> str:
    """Render a ValidationError as a short, model-readable bullet list
    (``- field.path: message``) instead of ``str(exc)``, which is noisy on
    a real multi-field payload. Capped at _MAX_VALIDATION_ERROR_LINES."""
    lines = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        lines.append(f"- {loc}: {err.get('msg', '')}")
    if len(lines) > _MAX_VALIDATION_ERROR_LINES:
        omitted = len(lines) - _MAX_VALIDATION_ERROR_LINES
        lines = [*lines[:_MAX_VALIDATION_ERROR_LINES], f"... ({omitted} more errors omitted)"]
    return "\n".join(lines)


def _to_responses_tool_schema(chat_completions_schema: dict[str, Any]) -> dict[str, Any]:
    """Reshape one of llm.tools's Chat-Completions-nested tool schemas
    (``{"type":"function","function":{"name":...,"parameters":...}}``) into
    the flat shape the Responses API expects
    (``{"type":"function","name":...,"parameters":...}``). Probed
    2026-09-06: gema's existing tool schemas work after this pure reshape,
    no other schema surgery needed."""
    function = chat_completions_schema["function"]
    flat: dict[str, Any] = {"type": "function", "name": function["name"]}
    if "description" in function:
        flat["description"] = function["description"]
    if "parameters" in function:
        flat["parameters"] = function["parameters"]
    return flat


def _responses_tool_schemas(names: list[str]) -> list[dict[str, Any]]:
    return [_to_responses_tool_schema(schema) for schema in tool_schemas(names)]


def _safe_execute_tool(name: str, arguments_raw: str) -> str:
    """Wrap execute_tool()'s dict-arguments call: unlike an unknown tool
    name (already handled inside execute_tool itself), malformed JSON
    arguments from the model, or an exception raised by the tool's own
    executor, would otherwise propagate straight out of the tool loop and
    abort the whole agent call. Feed the error back to the model as the
    tool's result instead -- same "never raises" contract execute_tool
    already promises for an unknown tool name, extended to cover these two
    additional failure modes."""
    try:
        arguments = json.loads(arguments_raw)
    except json.JSONDecodeError as exc:
        logger.warning("Tool %r called with malformed JSON arguments: %s", name, exc)
        return json.dumps({"found": False, "error": f"malformed arguments JSON: {exc}"})
    try:
        return execute_tool(name, arguments)
    except Exception as exc:  # tool executors are not guaranteed exception-free
        logger.warning("Tool %r raised during execution: %s", name, exc)
        return json.dumps({"found": False, "error": str(exc)})


class ResponsesLLMClient:
    """LLM client using OpenAI's Responses API (``POST /responses``) with
    native json_schema structured output.

    Implements the LLMClient Protocol (plus the same duck-typed
    ``complete_with_usage``/``complete_with_tools`` extensions
    InstructorLLMClient offers) for models that don't work at all over Chat
    Completions.
    """

    def __init__(self, config: LLMConfig, max_retries: int = 3) -> None:
        self._config = config
        self._max_retries = max_retries

        if config.seed is not None:
            logger.warning(
                "LLMConfig.seed=%r is set for model=%r, but the Responses "
                "API has no seed parameter (probed 2026-09-06: HTTP 400 "
                "'unknown parameter'); ResponsesLLMClient will never "
                "forward it.",
                config.seed,
                config.model,
            )

        raw_client_kwargs: dict[str, Any] = {
            "api_key": config.api_key.get_secret_value(),
            "timeout": config.timeout,
        }
        if config.base_url is not None:
            raw_client_kwargs["base_url"] = config.base_url

        self._raw_client = OpenAI(**raw_client_kwargs)

    @property
    def model(self) -> str:
        """Return the configured model name."""
        return self._config.model

    def _build_input(self, prompt: str, system_prompt: str | None) -> list[dict[str, Any]]:
        input_items: list[dict[str, Any]] = []
        if system_prompt is not None:
            input_items.append({"role": "system", "content": system_prompt})
        input_items.append({"role": "user", "content": prompt})
        return input_items

    def _reasoning_kwargs(self) -> dict[str, Any]:
        """``{"reasoning": {"effort": ...}}`` whenever reasoning_effort is
        set and isn't the "provider_default" sentinel; omitted entirely
        otherwise so the endpoint picks its own default. Every other literal
        value passes through verbatim, unvalidated against this specific
        model -- a 400 from an unsupported value is the config author's own
        explicit choice to surface, not something to silently rewrite."""
        effort = self._config.reasoning_effort
        if effort is None or effort == "provider_default":
            return {}
        return {"reasoning": {"effort": effort}}

    def complete(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> BaseModel:
        """Send prompt and return a validated Pydantic object."""
        result, _usage = self._complete_structured(
            self._build_input(prompt, system_prompt), response_model, **kwargs
        )
        return result

    def complete_with_usage(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> tuple[BaseModel, TokenUsage]:
        """Same as complete(), plus real token usage from the provider's
        response. Not part of the formal LLMClient Protocol -- see
        InstructorLLMClient.complete_with_usage's docstring for why."""
        return self._complete_structured(
            self._build_input(prompt, system_prompt), response_model, **kwargs
        )

    def _complete_structured(
        self,
        input_items: list[dict[str, Any]],
        response_model: type[BaseModel],
        extra_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[BaseModel, TokenUsage]:
        """Shared by complete()/complete_with_usage()/complete_with_tools()'s
        final call. Builds the native json_schema ``text=`` request, sends
        it, and validates the output -- hand-rolling a reask loop on
        failure (instructor's reask machinery doesn't apply to this wire
        format). Reused ``max_retries`` constructor param is *total
        attempts* (matching how instructor's own max_retries is
        documented), not a separate retry-count knob.

        ``extra_headers``: pass a pre-built header (from complete_with_tools,
        so the whole tool loop + this final call share one session ID) --
        when omitted, one is built fresh for this call alone, reused across
        just this call's own retry attempts.
        """
        text = _text_format(response_model)
        extra_body = _build_responses_extra_body(self._config)
        if extra_headers is None:
            extra_headers = _build_extra_headers(self._config)
        running_input = list(input_items)
        total_usage = TokenUsage()
        last_exc: ValidationError | ValueError | None = None

        for attempt in range(1, self._max_retries + 1):
            create_kwargs: dict[str, Any] = {
                "model": self._config.model,
                "input": running_input,
                "text": text,
                "temperature": self._config.temperature,
            }
            if self._config.max_tokens is not None:
                create_kwargs["max_output_tokens"] = self._config.max_tokens
            create_kwargs.update(self._reasoning_kwargs())
            if extra_body is not None:
                create_kwargs["extra_body"] = extra_body
            if extra_headers is not None:
                create_kwargs["extra_headers"] = extra_headers
            create_kwargs.update(kwargs)

            response = self._raw_client.responses.create(**create_kwargs)
            total_usage = _accumulate_usage(total_usage, response)

            status = getattr(response, "status", None)
            if status == "incomplete":
                incomplete_details = getattr(response, "incomplete_details", None)
                reason = (
                    getattr(incomplete_details, "reason", None)
                    if incomplete_details is not None
                    else None
                )
                msg = (
                    f"Responses API returned status='incomplete' (reason={reason!r}) "
                    f"for model={self._config.model!r}. Likely max_output_tokens or "
                    "reasoning_effort set too low for this response; not reasking -- "
                    "a token-budget truncation isn't fixed by asking again."
                )
                raise ValueError(msg)

            output_text = getattr(response, "output_text", None) or ""
            try:
                if not output_text:
                    msg = "Responses API returned empty output_text; no JSON to parse."
                    raise ValueError(msg)
                candidate = _extract_json(output_text)
                result = response_model.model_validate_json(candidate)
            except (ValidationError, ValueError) as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    break
                error_text = (
                    _format_validation_error(exc)
                    if isinstance(exc, ValidationError)
                    else "No JSON object found in the response output_text (it was empty)."
                )
                reask_turn: dict[str, Any] = {
                    "role": "user",
                    "content": (
                        f"Validation Error found:\n{error_text}\n"
                        "Return corrected JSON matching the schema."
                    ),
                }
                # Some OpenAI-compatible endpoints reject a message with
                # empty content with a 400 -- echoing output_text verbatim
                # when it's "" (the empty-output_text failure mode) would
                # turn a recoverable reask into a hard failure on exactly
                # the path meant to recover from it. The corrective user
                # turn above already states the output was empty; nothing
                # is lost by omitting the echo in that case.
                running_input = [
                    *running_input,
                    *([{"role": "assistant", "content": output_text}] if output_text else []),
                    reask_turn,
                ]
                logger.debug(
                    "Responses structured-output attempt %d/%d failed for model=%s; reasking.",
                    attempt,
                    self._max_retries,
                    self._config.model,
                )
                continue
            else:
                _raw_model = getattr(response, "model", None)
                resolved_model = _raw_model if isinstance(_raw_model, str) else ""
                total_usage = TokenUsage(
                    prompt_tokens=total_usage.prompt_tokens,
                    completion_tokens=total_usage.completion_tokens,
                    total_tokens=total_usage.total_tokens,
                    model=resolved_model,
                )
                return result, total_usage

        logger.error(
            "Responses structured-output failed after %d attempt(s) for model=%s; "
            "re-raising the last error.",
            self._max_retries,
            self._config.model,
        )
        if last_exc is None:
            # Unreachable: the loop above only exits via `break` (after
            # setting last_exc) or an earlier `return`/`raise`.
            msg = "Responses structured-output loop exited without an error to report"
            raise RuntimeError(msg)
        raise last_exc

    def complete_with_tools(
        self,
        prompt: str,
        response_model: type[BaseModel],
        tools: list[str],
        system_prompt: str | None = None,
        max_tool_rounds: int = 2,
        **kwargs: Any,
    ) -> tuple[BaseModel, TokenUsage]:
        """Agentic tool-call loop, then a final structured-output call.

        Not part of the formal LLMClient Protocol -- same optional,
        duck-typed extension as InstructorLLMClient.complete_with_tools,
        whose overall shape this mirrors (including the 2026-08-15
        collapse-tool-exchange-to-plain-text fix before the final call, for
        behavioral parity between the two clients even though the specific
        bug that motivated it is Chat-Completions-specific and can't occur
        here).

        Sends ``tools=`` + ``tool_choice="auto"`` on each round (a *forced*
        tool_choice returns 400 -- "only 'auto' is supported for
        tool_choice", probed 2026-09-06). The final call has no
        ``tools``/``tool_choice`` at all and goes through
        ``_complete_structured`` like ``complete()`` does.
        """
        base_input = self._build_input(prompt, system_prompt)
        loop_input: list[dict[str, Any]] = list(base_input)
        tool_exchange_log: list[tuple[str, str, str]] = []

        extra_body = _build_responses_extra_body(self._config)
        # Same ID for every round plus the final _complete_structured call
        # below -- one tool loop is one conversation, even across multiple
        # HTTP requests (mirrors instructor_client.complete_with_tools).
        extra_headers = _build_extra_headers(self._config)
        schemas = _responses_tool_schemas(tools)
        total_usage = TokenUsage()

        for round_num in range(max_tool_rounds):
            raw_kwargs: dict[str, Any] = {
                "model": self._config.model,
                "input": loop_input,
                "temperature": self._config.temperature,
                "tools": schemas,
                "tool_choice": "auto",
            }
            if self._config.max_tokens is not None:
                raw_kwargs["max_output_tokens"] = self._config.max_tokens
            raw_kwargs.update(self._reasoning_kwargs())
            if extra_body is not None:
                raw_kwargs["extra_body"] = extra_body
            if extra_headers is not None:
                raw_kwargs["extra_headers"] = extra_headers

            response = self._raw_client.responses.create(**raw_kwargs)
            total_usage = _accumulate_usage(total_usage, response)

            output_items = getattr(response, "output", None) or []
            function_calls = [
                item for item in output_items if getattr(item, "type", None) == "function_call"
            ]
            if not function_calls:
                logger.debug("Tool loop round %d: model stopped calling tools.", round_num + 1)
                break

            for call in function_calls:
                arguments_raw = getattr(call, "arguments", None) or "{}"
                result = _safe_execute_tool(call.name, arguments_raw)
                loop_input.append(
                    {
                        "type": "function_call",
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": arguments_raw,
                    }
                )
                loop_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": result,
                    }
                )
                tool_exchange_log.append((call.name, arguments_raw, result))
        else:
            logger.warning(
                "Tool loop hit max_tool_rounds=%d without the model stopping tool "
                "calls; proceeding to the final structured-output call anyway.",
                max_tool_rounds,
            )

        final_input = list(base_input)
        if tool_exchange_log:
            summary_lines = [
                f"- {name}({args}) -> {result}" for name, args, result in tool_exchange_log
            ]
            final_input.append(
                {
                    "role": "user",
                    "content": (
                        "During your reasoning you looked up the following via tool "
                        "calls -- use these results if relevant to your final answer:\n"
                        + "\n".join(summary_lines)
                    ),
                }
            )

        final_result, final_usage = self._complete_structured(
            final_input, response_model, extra_headers=extra_headers, **kwargs
        )
        total_usage = TokenUsage(
            prompt_tokens=total_usage.prompt_tokens + final_usage.prompt_tokens,
            completion_tokens=total_usage.completion_tokens + final_usage.completion_tokens,
            total_tokens=total_usage.total_tokens + final_usage.total_tokens,
            model=final_usage.model,
        )
        return final_result, total_usage

    def complete_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Send prompt and return raw text response. Bypasses structured
        output entirely -- no ``text=`` param at all."""
        extra_body = _build_responses_extra_body(self._config)
        extra_headers = _build_extra_headers(self._config)
        create_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "input": self._build_input(prompt, system_prompt),
            "temperature": self._config.temperature,
        }
        if self._config.max_tokens is not None:
            create_kwargs["max_output_tokens"] = self._config.max_tokens
        create_kwargs.update(self._reasoning_kwargs())
        if extra_body is not None:
            create_kwargs["extra_body"] = extra_body
        if extra_headers is not None:
            create_kwargs["extra_headers"] = extra_headers
        create_kwargs.update(kwargs)

        response = self._raw_client.responses.create(**create_kwargs)
        return getattr(response, "output_text", None) or ""


def _accumulate_usage(total_usage: TokenUsage, response: Any) -> TokenUsage:
    """Add one response's usage onto a running TokenUsage total.

    Field-name mapping: the Responses API reports ``input_tokens``/
    ``output_tokens``/``total_tokens`` (not Chat Completions'
    ``prompt_tokens``/``completion_tokens``). ``output_tokens`` already
    includes reasoning tokens (``output_tokens_details.reasoning_tokens``)
    -- logged at DEBUG only, never double-counted, never added as a new
    TokenUsage field (it's extra="forbid" and shared/cached, out of scope
    for this change).
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return total_usage
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    total_tokens = getattr(usage, "total_tokens", 0) or 0
    output_details = getattr(usage, "output_tokens_details", None)
    reasoning_tokens = getattr(output_details, "reasoning_tokens", None) if output_details else None
    if reasoning_tokens:
        logger.debug(
            "Responses call used %d reasoning tokens (of %d output tokens).",
            reasoning_tokens,
            output_tokens,
        )
    return TokenUsage(
        prompt_tokens=total_usage.prompt_tokens + input_tokens,
        completion_tokens=total_usage.completion_tokens + output_tokens,
        total_tokens=total_usage.total_tokens + total_tokens,
    )
