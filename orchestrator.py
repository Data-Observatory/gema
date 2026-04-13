"""Orchestrator for parallel agent execution with dependency resolution."""

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

from agents.base import BaseAgent
from agents.registry import AgentRegistry
from schemas.input_schema import DatasetInput
from schemas.settings_schema import AppSettings, ContextStrategy

logger = logging.getLogger(__name__)

_usage_lock = threading.Lock()


class Orchestrator:
    """Manages parallel agent execution with dependency resolution and context strategy."""

    RETRY_DELAYS: list[float] = [0.5, 1, 2, 3, 5, 7, 10]

    registry: AgentRegistry
    settings: AppSettings
    agents: dict[str, BaseAgent]

    def __init__(self, registry: AgentRegistry, settings: AppSettings):
        self.registry = registry
        self.settings = settings
        self.agents = registry.load_agents()
        self._lm_usage: dict[str, dict[str, int]] = {}
        self._per_agent_usage: dict[str, dict[str, Any]] = {}

    def run(self, input_data: DatasetInput) -> dict[str, Any]:
        all_outputs: dict[str, Any] = {}
        initial_input = input_data.model_dump()
        execution_waves = self.registry.get_execution_order()

        self._lm_usage = {}
        self._per_agent_usage = {}

        logger.info(f"Starting execution with {len(execution_waves)} waves")

        for wave_idx, wave in enumerate(execution_waves):
            logger.info(f"Executing wave {wave_idx + 1}/{len(execution_waves)}: {wave}")
            wave_outputs = self._execute_wave(wave, initial_input, all_outputs)
            all_outputs.update(wave_outputs)

        self._aggregate_usage()

        logger.info(f"Execution complete. {len(all_outputs)} agents executed")
        return all_outputs

    def get_lm_usage(self) -> dict[str, Any]:
        return self._lm_usage.copy()

    def get_per_agent_usage(self) -> dict[str, Any]:
        return self._per_agent_usage.copy()

    def _execute_wave(
        self,
        agent_ids: list[str],
        initial_input: dict[str, Any],
        all_outputs: dict[str, Any],
    ) -> dict[str, Any]:
        wave_outputs: dict[str, Any] = {}

        with ThreadPoolExecutor(max_workers=len(agent_ids)) as executor:
            future_to_agent: dict[
                Future[tuple[dict[str, Any], dict[str, Any]]], str
            ] = {}
            for agent_id in agent_ids:
                if agent_id not in self.agents:
                    logger.warning(f"Agent '{agent_id}' not found, skipping")
                    continue
                context = self._build_context_for_agent(
                    agent_id, all_outputs, initial_input
                )
                agent = self.agents[agent_id]
                future = executor.submit(
                    self._run_agent_with_usage, agent, agent_id, context
                )
                future_to_agent[future] = agent_id

            for future in as_completed(future_to_agent):
                agent_id = future_to_agent[future]
                try:
                    output, usage = future.result()
                    wave_outputs[agent_id] = output
                    self._record_agent_usage(agent_id, usage)
                    logger.info(f"Agent '{agent_id}' completed")
                except Exception as e:
                    logger.error(f"Agent '{agent_id}' failed: {e}")
                    wave_outputs[agent_id] = None

        return wave_outputs

    def _run_agent_with_usage(
        self, agent: BaseAgent, agent_id: str, context: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        last_exception: Exception | None = None
        for attempt in range(len(self.RETRY_DELAYS) + 1):
            try:
                output = agent.forward(context)
                usage = self._extract_usage_from_agent(agent)
                if attempt > 0:
                    logger.info(
                        f"Agent '{agent_id}' succeeded on attempt {attempt + 1}"
                    )
                return output, usage
            except Exception as e:
                error_type = type(e).__name__
                if error_type != "RateLimitError" and "RateLimitError" not in str(
                    type(e)
                ):
                    raise
                last_exception = e
                if attempt < len(self.RETRY_DELAYS):
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Agent '{agent_id}' rate limited (attempt {attempt + 1}/{len(self.RETRY_DELAYS) + 1}), retrying in {delay}s: {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Agent '{agent_id}' failed after {len(self.RETRY_DELAYS) + 1} attempts: {e}"
                    )
        if last_exception is None:
            raise RuntimeError(f"Agent '{agent_id}' failed without captured exception")
        raise last_exception

    def _extract_usage_from_agent(self, agent: BaseAgent) -> dict[str, Any]:
        try:
            if hasattr(agent, "_lm") and agent._lm.history:
                last_call = agent._lm.history[-1]
                raw_usage = last_call.get("usage", {})
                model = last_call.get("model", "unknown")
                if isinstance(raw_usage, dict):
                    return {
                        "model": model,
                        "prompt_tokens": raw_usage.get("prompt_tokens", 0),
                        "completion_tokens": raw_usage.get("completion_tokens", 0),
                        "total_tokens": raw_usage.get("total_tokens", 0),
                    }
        except Exception as e:
            logger.debug(f"Could not extract usage from agent: {e}")
        return {
            "model": "unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def _record_agent_usage(self, agent_id: str, usage: dict[str, Any]) -> None:
        with _usage_lock:
            self._per_agent_usage[agent_id] = usage
            model = usage.get("model", "unknown")
            if model not in self._lm_usage:
                self._lm_usage[model] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }
            self._lm_usage[model]["prompt_tokens"] += usage.get("prompt_tokens", 0)
            self._lm_usage[model]["completion_tokens"] += usage.get(
                "completion_tokens", 0
            )
            self._lm_usage[model]["total_tokens"] += usage.get("total_tokens", 0)

    def _aggregate_usage(self) -> None:
        pass

    def _build_context_for_agent(
        self,
        agent_id: str,
        all_outputs: dict[str, dict[str, Any]],
        initial_input: dict[str, Any],
    ) -> dict[str, Any]:
        if self.settings.context_strategy == ContextStrategy.ACCUMULATIVE:
            context = {**initial_input, **all_outputs}
        elif self.settings.context_strategy == ContextStrategy.LAYERED:
            if "explorer" in all_outputs:
                context = {**initial_input, **all_outputs.get("explorer", {})}
            else:
                context = initial_input.copy()
        else:
            context = {**initial_input, **all_outputs}

        logger.debug(
            f"Context for '{agent_id}': strategy={self.settings.context_strategy}"
        )
        return context
