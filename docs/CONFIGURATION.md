# Configuration Reference

## Pipeline Config (`agents.yaml`)

The main pipeline configuration file defines the schema, agents, providers, and
default settings. It validates against the `PipelineConfig` Pydantic model.

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_name` | `str` | yes | Schema to use (e.g. `datacite-4.6`) |
| `agents` | `list[AgentConfig]` | yes | Ordered list of agent definitions (at least 1) |
| `providers` | `list[ProviderConfig]` | yes | LLM provider connection settings (at least 1) |
| `default_provider` | `str` | no | Provider name used when an agent omits the `provider` field |
| `strategies` | `dict[str, str]` | no | Reserved for future strategy/override configuration |

### AgentConfig Fields

Each entry in the `agents` list supports:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | `str` | yes | — | Unique identifier (referenced by `depends_on`) |
| `name` | `str` | yes | — | Human-readable agent name |
| `description` | `str` | no | `""` | Optional description of the agent's purpose |
| `fields` | `list[str]` | yes | — | Metadata fields this agent is responsible for |
| `prompt` | `str` | yes | — | LLM prompt template (supports `{field}` placeholders via `str.format_map`) |
| `system_prompt` | `str` | no | `null` | Optional system-level instruction |
| `provider` | `str` | yes | — | Name of the provider to use (must match a provider entry) |
| `model` | `str` | no | `null` | Model name (e.g. `gpt-4`, `deepseek-v4-flash`) |
| `temperature` | `float` | no | `0.0` | LLM sampling temperature |
| `max_tokens` | `int` | no | `null` | Maximum tokens for the response |
| `depends_on` | `list[str]` | no | `[]` | Agent IDs that must complete before this agent runs |
| `use_chain_of_thought` | `bool` | no | `false` | Enable chain-of-thought prompting |

### ProviderConfig Fields

Each entry in the `providers` list supports:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | yes | — | Unique provider name (referenced by agents) |
| `base_url` | `str` | no | `null` | API base URL (e.g. `https://opencode.ai/zen/go/v1`) |
| `api_key_env` | `str` | yes | — | Environment variable name holding the API key |
| `default` | `bool` | no | `false` | Whether this is the default provider |

## Provider Config (`providers.yaml`)

A standalone provider configuration file that follows the same `ProviderConfig`
schema. This file is optional — providers can be inlined in `agents.yaml`.

```yaml
providers:
  - name: opencode
    api_key_env: OPENCODE_API_KEY
    base_url: https://opencode.ai/zen/go/v1
    default: true

  - name: openai
    api_key_env: OPENAI_API_KEY
    base_url: null
    default: false
```

## Migration from Legacy JSON

Legacy JSON configuration files (`config/legacy/andrea_v3.json` and older formats) can
be migrated to YAML using the built-in migration tool:

```python
from pathlib import Path
from metadata_enricher.config.migrate import migrate_json_to_yaml

migrate_json_to_yaml(Path("config/legacy/andrea_v3.json"))
```

This generates a `.yaml` file alongside the original JSON, preserving both.
Providers are loaded automatically from a sibling `providers.json` file.

The migration handles:
- Renaming `output_fields` → `fields`
- Renaming `prompt_template` → `prompt`
- Flattening the nested `llm_config` dict into top-level `model`, `provider`,
  `temperature`, and `max_tokens` fields
- Mapping `api_base` → `base_url` in provider configs

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | varies | API key for OpenAI provider |
| `ZAI_API_KEY` | varies | API key for ZAI provider |
| `OPENCODE_API_KEY` | varies | API key for OpenCode provider |
| `ANTHROPIC_API_KEY` | varies | API key for Anthropic provider |

Which variables are required depends on which providers are referenced by the
pipeline config.

## Full Example

```yaml
schema_name: datacite-4.6
default_provider: opencode
providers:
  - name: opencode
    api_key_env: OPENCODE_API_KEY
    base_url: https://opencode.ai/zen/go/v1
    default: true
agents:
  - id: core_metadata
    name: Core Metadata Extractor
    fields: [resource, titles, descriptions, languages, dates]
    prompt: "Extract metadata from {url}"
    provider: opencode
    model: deepseek-v4-flash
    temperature: 0.2
    depends_on: []
    use_chain_of_thought: true
```
