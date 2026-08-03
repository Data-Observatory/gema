# config/

Pydantic config models + YAML loader + JSON→YAML migration. **Pure data + I/O — no business logic.**

## STRUCTURE

```
config/
├── __init__.py
├── models.py     # ProviderConfig, AgentConfig, PipelineConfig (all extra="forbid")
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

All `model_config = ConfigDict(extra="forbid")`.

| Model | Required fields | Notes |
|-------|-----------------|-------|
| `ProviderConfig` | `name`, `api_key_env` | `base_url`, `default` optional |
| `AgentConfig` | `id`, `name`, `fields` (≥1), `prompt`, `provider` | `model`, `temperature=0.0`, `depends_on=[]`, `use_chain_of_thought=False` |
| `PipelineConfig` | `schema_name`, `agents` (≥1), `providers` (≥1) | `default_provider`, `strategies={}` |

**Cross-reference validation** (`PipelineConfig._validate_references`, lines 56-89):
- `default_provider` must exist in `providers`
- Every `agent.provider` must exist in `providers`
- Every `agent.depends_on` must exist in `agents`
- No duplicate agent IDs

## Loader (`loader.py`)

- `load_config(path)` — YAML → `${VAR}` env expansion → `PipelineConfig`.
- `find_config()` — search order:
  1. Explicit `--config` arg
  2. `./config/agents.yaml`
  3. `~/.config/metagen/agents.yaml`
  4. `$METAGEN_CONFIG` env var
- Raises on empty YAML (line 53-55).

## Migration (`migrate.py`)

`migrate_json_to_yaml(Path("config/legacy/andrea_v3.json"))` → writes `.yaml` sibling.

**Rules** (lines 90-94):
- **NEVER modifies original JSON** — read-only.
- `schema_name` hard-coded to `"datacite-4.6"`.
- `default_provider` chosen deterministically (first provider marked `default: true`, else first).

## ANTI-PATTERNS

- **NEVER add a field without `extra="forbid"`** — strict validation is the contract.
- **NEVER modify the original JSON during migration** — write a `.yaml` sibling.
- **NEVER skip cross-reference validation** — `PipelineConfig` raises at construction, fail-fast.
- **NEVER assume `model` is set on `AgentConfig`** — registry raises `ValueError` if `None`.

## NOTES

- YAML `${VAR}` expansion happens BEFORE pydantic validation.
- `PipelineConfig` validators run at model construction — invalid configs fail at `load_config()`, not at first use.
- `strategies` field exists on `PipelineConfig` but is not yet used in code (reserved for future merge strategies).
