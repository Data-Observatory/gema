# Configuration Reference

This is the config-and-CLI reference. For per-script flags (`record_golden.py`,
`run_live_eval.py`, `compare_models.py`, `validate_real_output.py`, ...), see
[`../scripts/README.md`](../scripts/README.md). Each tool's flags are documented there
only, not copied here.

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
| `list-providers` | `--config/-c` | Lists the runtime providers from a config's `providers:` block (marks `default_provider`) |
| `list-known-providers` | `--config/-c` | Lists the preset pool in `providers.yaml` (looked up as a sibling of the resolved `agents.yaml`). These are autofill presets, not runtime config |
| `validate <file>` | `--schema/-s` | Pre-flight only, no LLM call, no API key needed |
| `process <input_path>` | `--output/-o`, `--schema/-s`, `--config/-c`, `--allow-partial`, `--max-workers N`, `--export FORMAT` | The real run, which costs API tokens |

`process` is the one command that calls the LLM for real. `--allow-partial` writes
best-effort output even when some agents failed on a resource, instead of treating
any partial failure as a hard failure. `--max-workers` overrides the config's
`max_workers` for this run. Lower it first if a provider is rate-limiting (429s).

`--export FORMAT` (repeatable; choices `datacite`, `croissant`) writes an
additional export alongside the primary CDIF output, as a sibling file next to the
primary one (`<output>.datacite.json`, `<output>.croissant.json`). Both are pure
crosswalks (`metadata_enricher.exporters`) with no LLM call. Requires `--output`,
because there's no file to place a sibling next to when writing to stdout. A failed
export never blocks or corrupts the primary output; it's reported as a warning. Visor's
Run tab offers the same formats as download options (`visor/pages/run_page.py`), plus
Dataverse native JSON when `config/dataverse_export.yaml` loads. Dataverse has no CLI
flag.

```bash
uv run gema process examples/sample_input01.json -o output.json
uv run gema process tests/fixtures/do_catalog/inputs -o reports/manual/ --max-workers 1
uv run gema process examples/sample_input01.json -o output.json --export datacite --export croissant
```

Exit codes for `process`: `0` all resources fully succeeded · `1` every resource
failed · `2` a mix of success/failure, or any warning (incomplete field, PID that
doesn't resolve, failed export).

**About `dcterms:conformsTo`:** every generated record's `schema:subjectOf` declares
conformance to `https://w3id.org/cdif/core/1.0` and `https://w3id.org/cdif/discovery/1.0`.
Both URIs currently return 404. This is expected and isn't a gema bug: CDIF's
specification tells implementers to declare them, and they should resolve once CDIF
tags a release. See [`codata_mcp_croissant_cdifspecs.md` §8](codata_mcp_croissant_cdifspecs.md#8-conformance-assertion-despite-a-dead-link).

## Testing: which suite to run

| Suite | Command | Hits a real API? | Checks |
|-------|---------|:---:|--------|
| Unit + regression | `make test` | No | Component logic + cache-replayed golden outputs |
| Regression only | `make test-regression` | No | Cache-replayed golden outputs (`tests/fixtures/golden/`), `json-semantic-diff` ≥ 0.85 |
| Visor | `make test-visor` | No | Visor UI/bootstrap/settings (`visor/tests`, `-m "not live"`) |
| Live structural | `uv run pytest -m live` | Yes | Live pipeline returns *some* structured output |
| Live identifier resolution | `make live-identifier-check` | Yes (ROR/ISNI/ORCID) | Real registry matching; ORCID part needs `ORCID_CLIENT_ID`/`SECRET`, else skips |
| Real output validation | `uv run python scripts/validate_real_output.py` | Yes | A specific real run is actually usable: valid JSON, real content, PIDs that format-check *and resolve* live |
| Cross-model comparison | `uv run python scripts/compare_models.py` | Yes | Several models scored against human-reviewed ground truth (`tests/fixtures/do_catalog/`) |
| Semantic scoring | `make live-eval` (`scripts/run_live_eval.py`) | Yes | LLM-as-judge similarity to golden outputs |
| A/B diagnostic | `make ab-eval` | LLM: no (cache-replay); registries: yes | CDIF→DataCite export vs. the frozen pre-pivot DataCite baseline, informational only |
| Ground-truth shape | `make validate-gt` | No | Structural check of `tests/fixtures/do_catalog/ground_truth/` |

Full flags for the scripted ones: [`../scripts/README.md`](../scripts/README.md).

## Pipeline Config (`config/agents.yaml`)

The main pipeline configuration file defines the schema, agents, **runtime providers**,
and pipeline behavior. It validates against the `PipelineConfig` Pydantic model
(`src/metadata_enricher/config/models.py`, `extra="forbid"`, so an unknown key is an
error). Search order when `--config` isn't given: `./config/agents.yaml` →
`~/.config/gema/agents.yaml` → `$GEMA_CONFIG`. `${VAR}` references are expanded from the
environment before validation.

### Top-Level Fields

"Shipped" is the value in the repo's own `config/agents.yaml`, where it differs from the
model default.

| Field | Type | Default | Shipped | Description |
|-------|------|---------|---------|-------------|
| `schema_name` | `str` | required | `cdif-discovery` | Schema to use. `cdif-discovery` is the sole registered generation target; `datacite-4.6` is deregistered and exporter-only |
| `agents` | `list[AgentConfig]` | required | 5 agents | Agent definitions (at least 1) |
| `providers` | `list[ProviderConfig]` | required | 5 providers | LLM provider connection settings (at least 1). **This inline list is the only one the pipeline reads**; see [providers.yaml](#other-config-files) below |
| `default_provider` | `str` | `null` | `opencode` | Must name a provider in `providers`. Not a fallback: every agent must still set its own `provider`. Read for the `list-providers` "(default)" label and by `record_golden.py` (which API key to require) |
| `strategies` | `dict[str, str]` | `{}` | — | Unused by the pipeline. Only round-tripped by Visor's Agents-tab config download/upload |
| `max_workers` | `int` (≥1) | `4` | `1` | Max concurrent agent requests per resource (one wave's `ThreadPoolExecutor` size) when no provider/model override applies. Precedence: this → `ProviderConfig.max_workers` → that provider's `model_overrides[].max_workers`. Override per-run with `gema process --max-workers N` |
| `enable_content_fetch` | `bool` | `false` | `true` | Before any agent runs, fetch `resource.url` and put its cleaned page text into `fetched_content`. Skipped when the input already carries `fetched_content`; a failed fetch is silently tolerated |
| `enable_js_render_fallback` | `bool` | `false` | — | Only consulted with `enable_content_fetch`. When the static fetch comes back too thin (typically a JS-rendered page), retry via a headless render using the `obscura` binary (bundled into Visor builds, else must be on `PATH`) |
| `enable_doi_resolution` | `bool` | `false` | — | After merge, if `schema:identifier` is a DOI, backfill empty `schema:name`, creators, publisher, and `schema:datePublished` from Crossref |
| `enable_identifier_enrichment` | `bool` | `false` | `true` | Resolve creator/publisher/funder org names to ROR/ISNI (live API calls), and personal creators with a given/family name split to ORCID |
| `identifier_overrides_path` | `str` | `null` | `config/overrides.yaml` | Human-curated overrides file (see `scripts/curate_ror_isni.py`'s promote mode), checked before any ROR/ISNI network call. Resolved relative to the current working directory. A missing file is not an error. Only takes effect with `enable_identifier_enrichment` |
| `validate_pids` | `bool` | `true` | — | Check every DOI/ROR/ISNI/ORCID in the output for correct format on every run. Problems become warnings, never a hard failure |
| `validate_pids_live` | `bool` | `true` | — | On top of the format check, look each PID up against its registry to confirm it resolves. Set `false` to keep the format check but skip the network calls |
| `validate_shacl_conformance` | `bool` | `false` | — | Run the vendored CDIF Discovery SHACL shapes against the generated document, non-blocking (violations become warnings). Off by default because every currently recorded golden fixture fails it, mostly for reasons outside the pipeline's control, so enabling it surfaces warnings on essentially every run |

Validation at load time (fail-fast): `default_provider` and every `agent.provider` must
exist in `providers`; every `depends_on` must name a known agent; every `context_fields`
entry must be a field produced by a (transitive) `depends_on` ancestor; every `tools`
entry must exist in `llm/tools.py`'s `TOOL_REGISTRY`; no duplicate agent IDs, provider
names, or per-provider `model_overrides` models. An agent setting `reasoning_effort` on a
chat_completions model only logs a warning.

### AgentConfig Fields

Each entry in the `agents` list supports:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | `str` | yes | — | Unique identifier (referenced by `depends_on`) |
| `name` | `str` | yes | — | Human-readable agent name |
| `description` | `str` | no | `""` | Optional description of the agent's purpose |
| `fields` | `list[str]` | yes | — | Output fields this agent produces, as snake_case CDIF attribute names (`schema_name` for `schema:name`, `dcterms_bibliographic_citation`, ...) |
| `prompt` | `str` | yes | — | Prompt template. `{url}`, `{title}`, `{description}`, `{doi}`, `{fetched_content}`, `{detected_country}` and any extra input key are replaced as plain text. The resource itself is always appended under `=== RECURSO A PROCESAR ===` |
| `system_prompt` | `str` | no | `null` | Optional system-level instruction (the shipped config shares one via a YAML anchor) |
| `provider` | `str` | yes | — | Name of a provider in `providers` |
| `model` | `str` | no | `null` | Model name (e.g. `deepseek-v4-flash`). The registry raises if it ends up unset |
| `temperature` | `float` | no | `0.0` | Sampling temperature |
| `max_tokens` | `int` | no | `null` | Max response tokens. `null` omits it from the request |
| `reasoning_effort` | `none`/`minimal`/`low`/`medium`/`high`/`xhigh`/`provider_default` | no | `null` | Per-agent override of the provider/model's resolved reasoning effort. Only meaningful on the Responses API (`api_style: responses`). `provider_default` omits the reasoning block entirely |
| `depends_on` | `list[str]` | no | `[]` | Agent IDs that must complete before this agent runs (defines the waves) |
| `context_fields` | `list[str]` | no | `[]` | Field names from `depends_on` ancestors' merged output to surface in this agent's prompt (under `=== DATOS YA EXTRAÍDOS EN UN PASO ANTERIOR ===`) |
| `tools` | `list[str]` | no | `[]` | Tools this agent may call mid-reasoning before its final structured-output call. Currently only `lookup_organization` (ROR lookup, `llm/tools.py`) |
| `extra_body` | `dict` | no | `null` | Passed straight into the OpenAI-compatible request body, e.g. `{thinking: {type: disabled}}` for DeepSeek V4 on opencode. Part of the cache key |
| `use_chain_of_thought` | `bool` | no | `false` | Accepted but unused; it has no effect |

Example, the shipped `creators_publishers` agent (prompts abbreviated):

```yaml
- id: creators_publishers
  name: Creators and Publishers
  fields: [schema_creator, schema_contributor, schema_publisher]
  system_prompt: *shared_system_prompt
  prompt: |
    Tu tarea: identificar y estructurar todos los creadores, el publicador y los contribuyentes ...
  depends_on: [core_metadata]
  context_fields: [schema_name]
  tools: [lookup_organization]
  model: deepseek-v4-flash
  provider: opencode
  temperature: 0.0
  max_tokens: null
  extra_body:
    thinking:
      type: disabled
```

### ProviderConfig Fields

Each entry in the `providers` list supports:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | yes | — | Unique provider name (referenced by agents) |
| `api_key_env` | `str` | yes | — | Environment variable name holding the API key |
| `base_url` | `str` | no | `null` | API base URL (e.g. `https://opencode.ai/zen/go/v1`). `null` uses the OpenAI SDK default |
| `default` | `bool` | no | `false` | Fallback marker used by some scripts (`record_golden.py`, `run_live_eval.py`, `validate_real_output.py`) when `default_provider` is unset |
| `seed` | `int` | no | `null` | Sent as `seed` in the request body, and part of the cache key |
| `max_workers` | `int` (≥1) | no | `null` | Per-provider concurrency override (see top-level `max_workers`) |
| `session_header` | `str` | no | `null` | Header name stamped with a fresh random ID once per LLM call (OpenCode's required `x-opencode-session`). Never part of the cache key |
| `api_style` | `chat_completions`/`responses` | no | `chat_completions` | Wire format. `responses` routes to OpenAI's Responses API (`ResponsesLLMClient`) |
| `reasoning_effort` | same values as AgentConfig | no | `null` | Provider-level reasoning effort for Responses-API models. Built-in fallback when unset: `medium` |
| `model_overrides` | `list[ModelOverride]` | no | `[]` | Per-model settings, scoped to this provider only |

`ModelOverride` fields: `model` (required), `max_workers`, `api_style`,
`reasoning_effort`. Each is `null` by default, meaning "inherit from the provider".
Precedence, from least to most specific: built-in default → provider → model override →
(for `reasoning_effort` only) the agent's own field. For example, the shipped opencode
provider routes one model to the Responses API:

```yaml
- name: opencode
  api_key_env: OPENCODE_API_KEY
  base_url: https://opencode.ai/zen/go/v1
  default: true
  max_workers: 5
  session_header: x-opencode-session
  model_overrides:
  - model: muse-spark-1.3-contributor
    api_style: responses
    reasoning_effort: medium
```

Adding a provider means adding an entry here. No code change is needed for any
OpenAI-compatible endpoint.

## Other config files

| File | Read by | Purpose |
|------|---------|---------|
| `config/providers.yaml` | Visor's Settings tab "add a provider" picker; `gema list-known-providers` | A pool of `ProviderConfig` presets to autofill from. **The pipeline never reads it.** A provider only takes effect once it's in `agents.yaml`'s own `providers:` list (Visor adds it there in memory for the session) |
| `config/dataverse_export.yaml` | `exporters/dataverse.py` (`load_dataverse_export_config`), Visor | `enabled` (default `true`; `false` skips the LLM call and defaults Subject to `["Other"]` with a warning) and `agent`, a full `AgentConfig` for the one LLM-assisted step (classifying into Dataverse's fixed Subject vocabulary). Its `provider` must exist in the loaded `agents.yaml`'s `providers:`. Never runs through the orchestrator. Visor's Agents tab can edit its provider/model/temperature/reasoning effort |
| `config/eval.yaml` | Dev scripts only (`scripts/eval_common.py`, `run_live_eval.py`, `compare_models.py`, `judge_models.py`). Never read by `src/` | Defaults every corresponding CLI flag overrides: `judge` (LLM-as-judge `provider:model`, default `zai-coding-plan:glm-5.3`), `threshold` (`0.75`), `candidates` (model list for comparisons), `corpora` (named `do_catalog`/`golden` path presets). A missing file is treated as empty |
| `config/overrides.yaml` | `IdentifierResolver`, via `identifier_overrides_path` | Human-curated ROR/ISNI matches, written by `scripts/curate_ror_isni.py --promote-to`. Not present until a batch is promoted |
| `config/legacy/` | Migration and A/B diagnostic only | Pre-YAML JSON configs and the frozen pre-pivot `agents_datacite46.yaml` |

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

The output uses `schema_name: datacite-4.6` and DataCite field names, because legacy
configs are DataCite-shaped. That schema is no longer registered, so the migrated file
won't run until its field names are retargeted to CDIF and `schema_name` is changed to
`cdif-discovery` by hand. The migration logs a warning saying so.

## Environment Variables

Copy `.env.example` to `.env`. Only the keys for providers your agents actually use are
required.

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | varies | Provider `openrouter`. Visor's default, and the Dataverse export's default classifier provider |
| `OPENAI_API_KEY` | varies | Provider `openai` |
| `OPENCODE_API_KEY` | varies | Provider `opencode`, which every shipped agent uses from the CLI |
| `ANTHROPIC_API_KEY` | varies | Provider `anthropic` |
| `ZAI_API_KEY` | varies | Provider `zai-coding-plan`. Also the default live-eval judge (`config/eval.yaml`) |
| `OPENAI_BASE_URL` | optional | Picked up by the OpenAI SDK for a provider whose `base_url` is `null` |
| `ORCID_CLIENT_ID` / `ORCID_CLIENT_SECRET` | optional | Only needed for ORCID resolution of personal creators (part of `enable_identifier_enrichment`). Free self-service registration at [orcid.org/developer-tools](https://orcid.org/developer-tools). Unlike ROR/ISNI, ORCID's search API requires a bearer token even for read-only search. Without these, ORCID lookups are silently skipped (never an error) |
| `GEMA_CONFIG` | optional | Last-resort config path in the search order |
| `VISOR_NATIVE` / `VISOR_PORT` | optional | Visor only: `VISOR_NATIVE=0` serves a web page instead of a native window, on `VISOR_PORT` (default `8080`) |

## Full Example

A minimal working config with one agent and one provider:

```yaml
schema_name: cdif-discovery
default_provider: opencode
providers:
  - name: opencode
    api_key_env: OPENCODE_API_KEY
    base_url: https://opencode.ai/zen/go/v1
    session_header: x-opencode-session
agents:
  - id: core_metadata
    name: Core Metadata Extractor
    fields: [schema_name, schema_description, schema_identifier, schema_in_language, schema_date_published]
    prompt: "Extrae la metadata descriptiva del recurso {url}"
    provider: opencode
    model: deepseek-v4-flash
    temperature: 0.0
    extra_body:
      thinking:
        type: disabled
max_workers: 1
enable_content_fetch: true
```

See `config/agents.yaml` for the full 5-agent production config.
