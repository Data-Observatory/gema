# Configuration Reference

This is the config-and-CLI reference. For per-script flags (`record_golden.py`,
`run_live_eval.py`, `compare_geoportal.py`, `validate_real_output.py`, ...), see
[`../scripts/README.md`](../scripts/README.md) — flags live in one place per tool,
not copied here.

## `gema` CLI

```bash
uv run gema --help
uv run gema <command> --help
```

**Global options** (before the subcommand): `--config/-c PATH` (falls back to
auto-discovery), `--verbose/-v` (DEBUG logging), `--quiet/-q` (WARNING-only),
`--version`.

| Command | Flags | Notes |
|---------|-------|-------|
| `list-schemas` | — | Lists registered schemas |
| `list-providers` | `--config/-c` | Lists providers from a config |
| `validate <file>` | `--schema/-s` | Pre-flight only, no LLM call, no API key needed |
| `process <input_path>` | `--output/-o`, `--schema/-s`, `--config/-c`, `--allow-partial`, `--max-workers N` | The real run — costs API tokens |

`process` is the one command that calls the LLM for real. `--allow-partial` writes
best-effort output even when some agents failed on a resource, instead of treating
any partial failure as a hard failure. `--max-workers` overrides the config's
`max_workers` for this run — lower it first if a provider is rate-limiting (429s).

```bash
uv run gema process examples/sample_input01.json -o output.json
uv run gema process tests/fixtures/geoportal/inputs -o reports/manual/ --max-workers 1
```

Exit codes for `process`: `0` all resources fully succeeded · `1` every resource
failed · `2` a mix of success/failure/incomplete.

## Testing — pick the right one

| Suite | Command | Hits a real API? | Checks |
|-------|---------|:---:|--------|
| Unit + regression | `make test` | No | Component logic + cache-replayed golden outputs |
| Live structural | `uv run pytest -m live` | Yes | Live pipeline returns *some* structured output |
| Real output validation | `uv run python scripts/validate_real_output.py` | Yes | A specific real run is actually usable: valid JSON, real content, PIDs that format-check *and resolve* live |
| Cross-model comparison | `uv run python scripts/compare_geoportal.py` | Yes | Several models scored against human-reviewed ground truth |
| Semantic scoring | `uv run python scripts/run_live_eval.py` | Yes | LLM-as-judge similarity to golden outputs |

Full flags for the scripted ones: [`../scripts/README.md`](../scripts/README.md).

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
| `max_workers` | `int` | no | `4` | Max concurrent agent requests per resource (one wave's `ThreadPoolExecutor` size). Lower if the provider rate-limits (429s); override per-run with `gema process --max-workers N` |
| `enable_identifier_enrichment` | `bool` | no | `false` | Resolve creator/publisher/funder org names to ROR/ISNI (live API calls), and personal creators with a given/family name split to ORCID |
| `validate_pids` | `bool` | no | `true` | Check every DOI/ROR/ISNI found in the output for correct format on **every run** — no flag needed. Problems become `PipelineResult.warnings`, never a hard failure |
| `validate_pids_live` | `bool` | no | `true` | On top of the format check, actually look each PID up against doi.org/ror.org/isni.org to confirm it resolves. Set `false` to keep the format check but skip the live network calls |

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
| `ORCID_CLIENT_ID` / `ORCID_CLIENT_SECRET` | optional | Only needed for ORCID resolution of personal creators (part of `enable_identifier_enrichment`). Free self-service registration at [orcid.org/developer-tools](https://orcid.org/developer-tools) — unlike ROR/ISNI, ORCID's public API requires a bearer token even for read-only search. Without these set, ORCID lookups are silently skipped (never an error) |

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
