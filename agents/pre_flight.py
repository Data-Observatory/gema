"""Pre-flight validation for agent configurations."""

import logging
import re
from collections import Counter

from schemas.agent_config_schema import AgentsConfig, ProvidersConfig

logger = logging.getLogger(__name__)


class PreFlightValidator:
    """Validates agent configurations before pipeline execution.

    Catches configuration inconsistencies early with clear, formatted output,
    before any LLM calls are made.
    """

    def __init__(self, agents_config: AgentsConfig, providers_config: ProvidersConfig):
        self.agents_config = agents_config
        self.providers_config = providers_config
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def validate(self) -> tuple[list[str], list[str]]:
        """Run all validation checks. Returns (errors, warnings)."""
        self.errors = []
        self.warnings = []
        self.notes = []

        self._check_prompt_output_fields_mismatch()
        self._check_duplicate_prompt_templates()
        self._check_same_wave_key_collisions()
        self._check_unknown_providers()
        self._check_multi_field_output()

        return (self.errors, self.warnings)

    def print_report(self) -> None:
        """Print formatted validation report to stdout."""
        agents = self.agents_config.agents
        num_agents = len(agents)

        # Compute wave count via Kahn's algorithm
        waves = self._compute_waves()
        num_waves = len(waves)

        sep = "\u2550" * 63

        print(f"\n{sep}")
        print("  PRE-FLIGHT VALIDATION")
        print(f"  Config: {num_agents} agents | {num_waves} waves")
        print(sep)

        if not self.errors and not self.warnings and not self.notes:
            print("\n  \u2705 All checks passed. No issues found.")

        for error in self.errors:
            # Indent multi-line errors
            lines = error.split("\n")
            print(f"\n  \u274c ERROR: {lines[0]}")
            for line in lines[1:]:
                print(f"     {line.strip()}")

        for warning in self.warnings:
            lines = warning.split("\n")
            print(f"\n  \u26a0\ufe0f  WARNING: {lines[0]}")
            for line in lines[1:]:
                print(f"     {line.strip()}")

        for note in self.notes:
            lines = note.split("\n")
            print(f"\n  \u2139\ufe0f  INFO: {lines[0]}")
            for line in lines[1:]:
                print(f"     {line.strip()}")

        print(f"\n{sep}")
        e = len(self.errors)
        w = len(self.warnings)
        n = len(self.notes)
        print(f"  RESULT: {e} errors, {w} warnings, {n} notes")
        if self.errors:
            print("  \u26d4 Fix errors before running. Warnings are advisory.")
        else:
            print("  \u2705 No errors. Warnings are advisory.")
        print(f"{sep}\n")

    # ------------------------------------------------------------------
    # Validation checks
    # ------------------------------------------------------------------

    def _check_prompt_output_fields_mismatch(self) -> None:
        """Check if prompt_template content aligns with declared output_fields.

        Heuristic:
        1. Look for JSON output examples in prompt_template (``"key":`` patterns)
        2. Extract top-level keys from any found JSON examples
        3. Compare extracted keys against declared output_fields
        4. If overlap == 0 → ERROR (prompt likely belongs to a different agent)
        """
        for agent in self.agents_config.agents:
            prompt_keys = self._extract_keys_from_prompt(agent.prompt_template)

            if not prompt_keys:
                continue

            declared = set(agent.output_fields)
            prompt_key_set = set(prompt_keys)

            overlap = declared & prompt_key_set

            if len(overlap) == 0 and len(prompt_key_set) > 0:
                self.errors.append(
                    f"Agent '{agent.id}' prompt\u2194output_fields mismatch\n"
                    f"     Declared output_fields: {sorted(declared)}\n"
                    f"     Prompt instructs extraction of: {sorted(prompt_key_set)}\n"
                    f"     \u2192 Prompt may belong to a different agent"
                )
            # No elif — partial mismatch removed as all false positives

    def _extract_keys_from_prompt(self, prompt: str) -> list[str]:
        """Extract top-level JSON keys from output examples in a prompt template.

        Looks for ``"key":`` patterns that resemble JSON output structure.
        Filters out common non-field keys (instruction metadata).
        """
        keys: set[str] = set()

        json_key_pattern = re.findall(r'"(\w+)"\s*:', prompt)
        if json_key_pattern:
            field_keys = {k for k in json_key_pattern if k.islower() or "_" in k}
            non_field = {
                "paso",
                "paso_1",
                "paso_2",
                "regla",
                "ejemplo",
                "formato",
                "instruccion",
                "nota",
                "importante",
                "contexto",
                "tipo",
                "campo",
                "valor",
                "opcional",
                "obligatorio",
                "descripcion",
                "ejemplo_json",
                "salida",
                "entrada",
                "paso_3",
                "paso_4",
                "paso_5",
                "paso_6",
                "paso_7",
                "paso_8",
                "paso_9",
                "paso_10",
                "notas",
                "instrucciones",
                "datos",
            }
            field_keys -= non_field
            keys.update(field_keys)

        return list(keys)

    def _check_duplicate_prompt_templates(self) -> None:
        """Check if two agents share identical prompt_template content."""
        agents_by_prompt: dict[str, list[str]] = {}
        for agent in self.agents_config.agents:
            normalized = agent.prompt_template.strip()
            agents_by_prompt.setdefault(normalized, []).append(agent.id)

        for prompt, agent_ids in agents_by_prompt.items():
            if len(agent_ids) > 1:
                self.errors.append(
                    f"Duplicate prompt template\n"
                    f"     Agents {agent_ids} share identical prompts\n"
                    f"     \u2192 Both will produce the same output structure"
                )

    def _check_same_wave_key_collisions(self) -> None:
        """Check for output_fields collisions between agents in the same execution wave."""
        waves = self._compute_waves()

        agent_map = {a.id: a for a in self.agents_config.agents}
        for wave_idx, wave in enumerate(waves):
            field_to_agents: dict[str, list[str]] = {}
            for agent_id in wave:
                if agent_id in agent_map:
                    for field in agent_map[agent_id].output_fields:
                        field_to_agents.setdefault(field, []).append(agent_id)

            for field, agent_list in field_to_agents.items():
                if len(agent_list) > 1:
                    self.warnings.append(
                        f"Same-wave key collision (wave {wave_idx + 1})\n"
                        f"     Field '{field}' produced by: {agent_list}\n"
                        f"     \u2192 Merge order is non-deterministic"
                    )

    def _check_unknown_providers(self) -> None:
        """Check that all agents reference known providers."""
        available = list(self.providers_config.providers.keys())
        for agent in self.agents_config.agents:
            if agent.llm_config.provider:
                provider = self.providers_config.get_provider(agent.llm_config.provider)
                if provider is None:
                    self.errors.append(
                        f"Agent '{agent.id}' references unknown provider '{agent.llm_config.provider}'\n"
                        f"     Available providers: {available}"
                    )

    def _check_multi_field_output(self) -> None:
        """Info note for agents with multiple output fields."""
        for agent in self.agents_config.agents:
            if len(agent.output_fields) > 1:
                self.notes.append(
                    f"Agent '{agent.id}' has {len(agent.output_fields)} output_fields (multiple): {agent.output_fields}"
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_waves(self) -> list[list[str]]:
        """Compute execution waves using Kahn's topological sort algorithm.

        Replicates the same logic used in AgentRegistry.get_execution_order()
        but works directly with AgentsConfig data.
        """
        agents = self.agents_config.agents
        agent_ids = {a.id for a in agents}

        in_degree: dict[str, int] = {a.id: 0 for a in agents}
        graph: dict[str, list[str]] = {a.id: [] for a in agents}

        for agent in agents:
            for dep in agent.depends_on:
                if dep in agent_ids:
                    graph[dep].append(agent.id)
                    in_degree[agent.id] += 1

        waves: list[list[str]] = []
        remaining = set(in_degree.keys())

        while remaining:
            ready = [aid for aid in remaining if in_degree[aid] == 0]
            if not ready:
                break  # Circular dependency — not our job to report
            waves.append(ready)
            for aid in ready:
                remaining.remove(aid)
                for neighbor in graph[aid]:
                    in_degree[neighbor] -= 1

        return waves
