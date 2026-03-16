"""Base agent class using DSPy."""

import json
import logging
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
    ):
        super().__init__()
        self.config = config
        self.output_model = output_model
        self.api_key = api_key
        self.logger = logging.getLogger(f"agents.{config.id}")

        self._providers_config = providers_config or ProvidersConfig.load()
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
        model = self.config.model
        provider_name = self.config.provider
        lm_kwargs: dict[str, Any] = {"cache": False}

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

        return dspy.LM(model, **lm_kwargs)

    def forward(self, context: dict[str, Any]) -> dict[str, Any]:
        self.logger.info(
            f"Agent '{self.config.id}' starting with model '{self.config.model}'"
        )

        context_str = json.dumps(context, ensure_ascii=False, default=str)

        try:
            with dspy.context(lm=self._lm):
                result = self.predictor(context=context_str)

            output = self._parse_and_validate(result.output)
            self.logger.info(f"Agent '{self.config.id}' completed successfully")
            return output

        except json.JSONDecodeError as e:
            self.logger.error(f"Agent '{self.config.id}' produced invalid JSON: {e}")
            return self._empty_output()
        except ValidationError as e:
            self.logger.error(f"Agent '{self.config.id}' output validation failed: {e}")
            return self._empty_output()
        except Exception as e:
            self.logger.error(f"Agent '{self.config.id}' failed: {e}")
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
