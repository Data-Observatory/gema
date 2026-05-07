"""Base agent class using DSPy."""

import json
import logging
import time
from typing import Any, Type

import dspy
from pydantic import BaseModel, ValidationError

from schemas.agent_config_schema import AgentConfig, ProvidersConfig

logger = logging.getLogger(__name__)


class BaseAgent(dspy.Module):
    """Base agent with configurable behavior and optional typed validation."""

    def __init__(
        self,
        config: AgentConfig,
        output_model: Type[BaseModel] | None = None,
        api_key: str = "",
        providers_config: ProvidersConfig | None = None,
        cache_enabled: bool = True,
    ):
        super().__init__()
        self.config = config
        self.output_model = output_model
        self.api_key = api_key
        self.logger = logging.getLogger(f"agents.{config.id}")

        self._providers_config = providers_config or ProvidersConfig.load()
        self._cache_enabled = cache_enabled
        self._lm = self._create_lm()

        signature = self._build_signature()

        if config.use_chain_of_thought:
            self.predictor = dspy.ChainOfThought(signature)
        else:
            self.predictor = dspy.Predict(signature)

    def _build_signature(self) -> type[dspy.Signature]:
        output_desc = ", ".join(self.config.output_fields)
        prompt = self.config.prompt_template

        class DynamicSignature(dspy.Signature):
            context: str = dspy.InputField(
                desc="JSON context with available information"
            )
            output: str = dspy.OutputField(desc=f"JSON with fields: {output_desc}")

        DynamicSignature.__doc__ = prompt
        return DynamicSignature

    def _create_lm(self) -> dspy.LM:
        llm_config = self.config.llm_config
        model = llm_config.model
        provider_name = llm_config.provider
        lm_kwargs: dict[str, Any] = {"cache": self._cache_enabled}

        if provider_name:
            provider = self._providers_config.get_provider(provider_name)
            if provider:
                lm_kwargs["api_key"] = provider.get_api_key()
                if provider.api_base:
                    model = f"openai/{model}"
                    lm_kwargs["api_base"] = provider.api_base
            else:
                lm_kwargs["api_key"] = self.api_key
        else:
            lm_kwargs["api_key"] = self.api_key

        # Add generation parameters if explicitly set
        if llm_config.temperature is not None:
            lm_kwargs["temperature"] = llm_config.temperature
        if llm_config.max_tokens is not None:
            lm_kwargs["max_tokens"] = llm_config.max_tokens
        if llm_config.timeout is not None:
            lm_kwargs["timeout"] = llm_config.timeout

        return dspy.LM(model, **lm_kwargs)

    def forward(self, context: dict[str, Any]) -> dict[str, Any]:
        t_start = time.perf_counter()
        model = self.config.llm_config.model
        provider = self.config.llm_config.provider or "default"

        self.logger.info(
            f"[PREPARE] Agent '{self.config.id}' preparing context — model={model}, provider={provider}"
        )

        context_str = json.dumps(context, ensure_ascii=False, default=str)
        self.logger.info(
            f"[REQUEST] Agent '{self.config.id}' sending request — {len(context_str)} chars context, model={model}"
        )
        self.logger.info(
            f"[WAITING] Agent '{self.config.id}' waiting for LLM response..."
        )

        try:
            t_llm = time.perf_counter()
            with dspy.context(lm=self._lm):
                result = self.predictor(context=context_str)
            llm_elapsed = time.perf_counter() - t_llm

            response_text = result.output if hasattr(result, "output") else str(result)
            self.logger.info(
                f"[RESPONSE] Agent '{self.config.id}' LLM responded in {llm_elapsed:.2f}s — {len(response_text)} chars response"
            )

            self.logger.info(f"[PARSING] Agent '{self.config.id}' parsing output...")
            output = self._parse_and_validate(result.output)

            total_elapsed = time.perf_counter() - t_start
            self.logger.info(
                f"[DONE] Agent '{self.config.id}' completed successfully in {total_elapsed:.2f}s"
            )
            return output

        except json.JSONDecodeError as e:
            total_elapsed = time.perf_counter() - t_start
            self.logger.error(
                f"[FAILED] Agent '{self.config.id}' produced invalid JSON after {total_elapsed:.2f}s: {e}"
            )
            return self._empty_output()
        except ValidationError as e:
            total_elapsed = time.perf_counter() - t_start
            self.logger.error(
                f"[FAILED] Agent '{self.config.id}' output validation failed after {total_elapsed:.2f}s: {e}"
            )
            return self._empty_output()
        except Exception as e:
            total_elapsed = time.perf_counter() - t_start
            self.logger.error(
                f"[FAILED] Agent '{self.config.id}' failed after {total_elapsed:.2f}s: {e}"
            )
            raise

    def _parse_and_validate(self, raw_output: Any) -> dict[str, Any]:
        parsed = self._parse_output(raw_output)

        if self.output_model:
            validated = self.output_model.model_validate(parsed)
            return validated.model_dump(exclude_none=True, exclude_unset=True)

        return parsed

    def _parse_output(self, raw_output: Any) -> dict[str, Any]:
        if isinstance(raw_output, dict):
            return raw_output
        if isinstance(raw_output, BaseModel):
            return raw_output.model_dump()
        if isinstance(raw_output, str):
            try:
                return json.loads(raw_output)
            except json.JSONDecodeError:
                return self._empty_output()
        return self._empty_output()

    def _empty_output(self) -> dict[str, Any]:
        return {field: None for field in self.config.output_fields}
