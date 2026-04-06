"""Agent and provider configuration schemas."""

import json
import os
from pathlib import Path

from typing import Any

from pydantic import BaseModel, Field, model_validator

DEFAULT_MODEL = "glm-5"


class LLMConfig(BaseModel):
    model: str = Field(default="glm-5")
    provider: str | None = Field(default=None)
    temperature: float | None = Field(default=0.1)
    max_tokens: int | None = Field(default=None)


class ProviderConfig(BaseModel):
    api_base: str | None = None
    api_key_env: str = "LLM_API_KEY"

    def get_api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


class ProvidersConfig(BaseModel):
    providers: dict[str, ProviderConfig]

    @classmethod
    def load(cls, path: str = "config/providers.json") -> "ProvidersConfig":
        config_path = Path(path)
        if not config_path.exists():
            return cls(providers={})
        with open(config_path) as f:
            data = json.load(f)
        return cls(**data)

    def get_provider(self, name: str) -> ProviderConfig | None:
        provider_name = name.split("/")[0] if "/" in name else name
        return self.providers.get(provider_name)


class AgentConfig(BaseModel):
    id: str
    name: str
    description: str
    output_fields: list[str]
    prompt_template: str
    depends_on: list[str] = []
    use_chain_of_thought: bool = True
    llm_config: LLMConfig = LLMConfig()

    @model_validator(mode="before")
    @classmethod
    def migrate_flat_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "model" in data or "provider" in data:
                data = data.copy()
                llm_config = data.pop("llm_config", {})
                if "model" in data:
                    llm_config["model"] = data.pop("model")
                if "provider" in data:
                    llm_config["provider"] = data.pop("provider")
                data["llm_config"] = llm_config
        return data


class AgentsConfig(BaseModel):
    agents: list[AgentConfig]

    def validate_dependencies(self) -> list[str]:
        errors = []
        agent_ids = {a.id for a in self.agents}

        for agent in self.agents:
            for dep in agent.depends_on:
                if dep not in agent_ids:
                    errors.append(
                        f"Agent '{agent.id}' depends on unknown agent '{dep}'"
                    )

        visited = set()
        rec_stack = set()

        def has_cycle(agent_id: str) -> bool:
            visited.add(agent_id)
            rec_stack.add(agent_id)

            agent_map = {a.id: a for a in self.agents}
            if agent_id in agent_map:
                for dep in agent_map[agent_id].depends_on:
                    if dep not in visited:
                        if has_cycle(dep):
                            return True
                    elif dep in rec_stack:
                        return True

            rec_stack.remove(agent_id)
            return False

        for agent in self.agents:
            if agent.id not in visited:
                if has_cycle(agent.id):
                    errors.append(
                        f"Circular dependency detected involving '{agent.id}'"
                    )

        return errors
