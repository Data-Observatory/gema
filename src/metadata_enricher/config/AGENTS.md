# config/

Pydantic config models + YAML loader + JSON→YAML migration. **Pure data + I/O — no business logic.**

## STRUCTURE

```
config/
├── __init__.py
├── models.py     # ModelOverride, ProviderConfig, AgentConfig, PipelineConfig, DataverseExportConfig (all extra="forbid")
├── loader.py     # load_config() YAML→PipelineConfig, find_config() search
└── migrate.py    # migrate_json_to_yaml() — legacy JSON → YAML converter
```

> ⚠ Do NOT confuse with `/config/` at repo root — that's runtime user YAML/JSON files. This dir is the **loader code**.

## WHERE TO LOOK

| Task | File |
|------|------|
| Add new agent config field | `models.py:AgentConfig` (then update YAML schema in `/config/agents.yaml`) |
| Add new provider config field | `models.py:ProviderConfig` |
| Change YAML env var expansion | `loader.py:50` (`os.path.expandvars`) |
| Add new config search path | `loader.py:find_config()` |
| Fix migration bug | `migrate.py:migrate_json_to_yaml()` |

## Models (`models.py`)

All `model_config = ConfigDict(extra="forbid")`. User-facing field reference:
[`docs/CONFIGURATION.md`](../../../docs/CONFIGURATION.md).

| Model | Required fields | Optional fields (default) |
|-------|-----------------|---------------------------|
| `ModelOverride` | `model` | `max_workers`, `api_style`, `reasoning_effort` (all `None` = inherit from provider) |
| `ProviderConfig` | `name`, `api_key_env` | `base_url`, `default=False`, `seed`, `max_workers`, `model_overrides=[]`, `session_header`, `api_style="chat_completions"`, `reasoning_effort` |
| `AgentConfig` | `id`, `name`, `fields` (≥1), `prompt`, `provider` | `description=""`, `system_prompt`, `model`, `temperature=0.0`, `max_tokens`, `reasoning_effort`, `depends_on=[]`, `context_fields=[]`, `use_chain_of_thought=False` (unused, no effect), `extra_body`, `tools=[]` |
| `PipelineConfig` | `schema_name`, `agents` (≥1), `providers` (≥1) | `default_provider`, `strategies={}` (unused by the pipeline), `max_workers=4`, `enable_identifier_enrichment=False`, `identifier_overrides_path`, `enable_content_fetch=False`, `enable_js_render_fallback=False`, `enable_doi_resolution=False`, `validate_pids=True`, `validate_pids_live=True`, `validate_shacl_conformance=False` |
| `DataverseExportConfig` | `agent` (an `AgentConfig`) | `enabled=True`; `validate_provider_exists(names)` is called by the caller, since this model has no providers list of its own |

Type aliases: `ApiStyle = Literal["chat_completions", "responses"]`, `ReasoningEffort`
(OpenAI's values plus the gema-only `"provider_default"` sentinel, meaning "omit the
reasoning block"). `DEFAULT_RESPONSES_REASONING_EFFORT = "medium"`.

**Cascading resolvers** (the only place these values are resolved; never special-case a
provider/model name elsewhere):
- `ProviderConfig.effective_api_style(model)`: provider → model override.
- `ProviderConfig.effective_reasoning_effort(model)`: built-in default → provider → model override (the agent's own `reasoning_effort` is applied on top by the caller).
- `PipelineConfig.effective_max_workers(provider, model)`: global → provider → model override.
- `find_model_override_elsewhere()`: misconfiguration hint for Visor (another provider carries an override for this model that the assigned provider wouldn't resolve to). Never blocks anything.

**Cross-reference validation** (`PipelineConfig._validate_references`, from line ~297), all raising `ValueError` at construction:
- `default_provider` must exist in `providers`
- No duplicate `model_overrides` models within one provider
- Every `agent.provider` must exist in `providers`
- Every `agent.depends_on` must exist in `agents`
- Every `agent.context_fields` entry must be a field of some **transitive** `depends_on` ancestor (walks the dependency chain, not just direct deps)
- Every `agent.tools` entry must exist in `llm/tools.py`'s `TOOL_REGISTRY` (imported locally so `models.py` stays import-light)
- No duplicate agent IDs, no duplicate provider names
- Warning only (not an error): an agent sets `reasoning_effort` but resolves to a chat_completions model

## Loader (`loader.py`)

- `load_config(path)` — YAML → `${VAR}` env expansion → `PipelineConfig`.
- `find_config()` — search order:
  1. Explicit `--config` arg
  2. `./config/agents.yaml`
  3. `~/.config/gema/agents.yaml`
  4. `$GEMA_CONFIG` env var
- Raises on empty YAML (line 53-55).

## Migration (`migrate.py`)

`migrate_json_to_yaml(Path("config/legacy/andrea_v3.json"))` → writes `.yaml` sibling.

**Rules** (see `migrate_json_to_yaml()`'s docstring):
- **NEVER modifies original JSON** — read-only.
- `schema_name` hard-coded to `"datacite-4.6"` (legacy JSON configs are DataCite-shaped; emitting `cdif-discovery` over DataCite field lists would produce a guaranteed-broken config). Since the CDIF pivot, this schema name is no longer registered — `migrate.py` logs a `logger.warning` at migration time saying so.
- `default_provider` chosen deterministically: the alphabetically first provider name referenced by the migrated agents.

## ANTI-PATTERNS

- **NEVER add a field without `extra="forbid"`** — strict validation is the contract.
- **NEVER modify the original JSON during migration** — write a `.yaml` sibling.
- **NEVER skip cross-reference validation** — `PipelineConfig` raises at construction, fail-fast.
- **NEVER assume `model` is set on `AgentConfig`** — registry raises `ValueError` if `None`.

## NOTES

- YAML `${VAR}` expansion happens BEFORE pydantic validation.
- `PipelineConfig` validators run at model construction — invalid configs fail at `load_config()`, not at first use.
- `strategies` field exists on `PipelineConfig` but nothing in the pipeline reads it; only Visor's Agents-tab upload copies it across.
- Runtime providers come only from `agents.yaml`'s own `providers:` list. Repo-root `config/providers.yaml` is parsed elsewhere (`cli.py:list_known_providers`, `visor/bootstrap.py`) as a preset pool, never by `load_config()`.
