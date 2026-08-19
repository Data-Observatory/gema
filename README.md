# Gema

[![CI](https://github.com/Data-Observatory/gema/actions/workflows/ci.yml/badge.svg)](https://github.com/Data-Observatory/gema/actions/workflows/ci.yml)
[![Visor Build](https://github.com/Data-Observatory/gema/actions/workflows/visor-build.yml/badge.svg)](https://github.com/Data-Observatory/gema/actions/workflows/visor-build.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![uv](https://img.shields.io/badge/managed%20by-uv-3d3d3d)](https://docs.astral.sh/uv/)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL%20v3-blue.svg)](LICENSE)

Automatic metadata generation for scholarly resources using LLM agents,
producing DataCite 4.6 records from minimal resource descriptions (URL,
title, description, DOI).

Two ways to use it:

- **Visor** — a point-and-click desktop app. No terminal, no Python
  knowledge required.
- **`gema`** — a CLI/library for scripting, batch jobs, and CI.

---

# For Users

## Visor (desktop app)

Visor runs the same pipeline behind a simple three-tab UI: **Settings**
(API keys) -> **Agents** (review/edit what each agent does) -> **Run**
(paste or upload a resource, get metadata back). No file editing needed —
Visor ships with a working default configuration.

### Run it from source (works today, any OS)

```bash
git clone <repo-url>
cd gema
uv sync --extra dev --extra visor --group visor-build
uv run python -m visor.app            # opens a native desktop window
```

Under WSL, or any environment without a native window toolkit, serve it as
a plain web page instead:

```bash
VISOR_NATIVE=0 uv run python -m visor.app
# optional: pick the port
VISOR_PORT=8001 VISOR_NATIVE=0 uv run python -m visor.app
```

It prints a URL (`http://127.0.0.1:<port>`) — open that in a browser. On
first run it seeds a writable config at `~/.config/gema/agents.yaml`
and defaults every agent to OpenRouter (see
[Provider defaults](#provider-defaults-opencode-vs-openrouter) below); add
your `OPENROUTER_API_KEY` on the Settings tab and you're ready to run.

### Building a standalone installer (no Python required by the end user)

Prebuilt installers aren't published as a public release yet. Build one
yourself, or grab the artifact from a `visor-build.yml` workflow run — see
[`visor/BUILD.md`](visor/BUILD.md) for the full build/packaging/CI guide
(Windows `.exe` installer, macOS `.dmg`, portable single-file builds, and
the known platform caveats).

## The `gema` CLI

### Prerequisites

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
git clone <repo-url>
cd gema
uv sync --extra dev
```

### Configuration

1. Copy `.env.example` to `.env` and fill in at least one provider's API key:

   ```bash
   cp .env.example .env
   # Edit .env with your OPENROUTER_API_KEY, OPENAI_API_KEY, OPENCODE_API_KEY, or ANTHROPIC_API_KEY
   ```

2. The default config is at `config/agents.yaml` (5 agents for DataCite 4.6 metadata).
   Provider connection settings are defined in `config/providers.yaml`.

### Processing your own dataset

This is the real workflow — not a test fixture, an actual new resource you want
DataCite metadata for. Everything here is `uv run gema ...`; no test suite
involved.

**1. Describe the resource as JSON.** Minimum useful fields: `url`, `title`,
`description`. Add `doi` if it already has one, `fetched_content` (raw HTML/text
from the resource's landing page) if you have it — the agents use whatever you
give them. Any other key you add is passed through too (`ResourceDescription`
accepts extra fields, e.g. `publisher`, `frequency` — see `examples/sample_input01.json`
for a real one).

```json
{
  "url": "https://example.org/dataset/rainfall-2024",
  "title": "Annual Rainfall Measurements 2024",
  "description": "Monthly rainfall totals by station, national weather service.",
  "publisher": "Servicio Meteorológico Nacional",
  "context_hints": "Published in 2024. Contains 3 data files (CSV, XLSX, PDF). 4 authors listed in the source repository, not mentioned on the page."
}
```

`context_hints` is a free-text field for anything you already know that
isn't stated in the resource's own content — the agents treat it as
trusted, externally-verified evidence, but the resource's own text always
wins if it explicitly says something different.

Save it as e.g. `my_dataset.json`.

**2. Pre-flight check it — no API key needed, no cost.**

```bash
uv run gema validate my_dataset.json
```

Fixes anything the schema needs before you spend a real API call.

**3. Run it for real.** This calls the LLM (costs tokens) and, if
`enable_identifier_enrichment` is on in your config (it is by default in
`config/agents.yaml`), also resolves creator/publisher/funder orgs against ROR/ISNI
live, and every PID in the result gets checked for real (format + live registry
lookup — see the testing-tiers table in [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)).

```bash
uv run gema process my_dataset.json --output my_dataset_metadata.json
```

**4. Read the result.** `my_dataset_metadata.json` is the full DataCite 4.6 record.
Check stderr too — that's where `gema` prints anything worth knowing:

```
Processed 1/1 resources successfully
```

or, if something's off (a missing field, a PID that doesn't actually resolve):

```
Warning: my_dataset.json has incomplete fields:
  - ROR does not resolve: 'https://ror.org/badid00' (creators[0].name_identifiers[0])
```

That warning does NOT mean the run failed — exit code is `2` (success with
caveats) rather than `1` (hard failure). The file was still written; that specific
field just needs a human look.

**5. Got a whole folder of new datasets, not just one?** Point at the directory
instead of a file — output then needs to be a directory too, one JSON per input:

```bash
uv run gema process my_datasets/ --output my_datasets_output/
```

**6. Want the detailed human-reviewer-style report** (is the abstract real, are
subjects/topics populated, every PID checked) **instead of just the warnings above?**

```bash
uv run python scripts/validate_real_output.py --input my_dataset.json
```

That's the tool from the previous section on this exact workflow — same live run,
richer report. See [`scripts/README.md`](scripts/README.md#validate_real_outputpy).

---

For the full CLI/config flag reference: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
For flags on `record_golden.py`, `run_live_eval.py`, `sample_corpus.py`,
`generate_inputs.py`, `compare_models.py`, `judge_models.py`, and
`validate_real_output.py`: [`scripts/README.md`](scripts/README.md).

---

# For Developers

## Architecture

```
Input JSON -> FilesystemInputSource -> ResourceDescription
                                             |
                                    PreFlightValidator <- Schema Registry -> DataCiteSchema46
                                             |
                AgentRegistry <- PipelineConfig -> ProviderConfig -> LLMClient factory
                                             |
                       Orchestrator (Kahn topological sort + ThreadPoolExecutor)
                                             |
                          MetadataMerger -> MetadataDocument -> OutputWriter -> JSON
```

### Key Design Decisions

- **Pluggable schemas**: DataCite 4.6 ships as reference implementation. New schemas implement the `Schema` Protocol.
- **OpenAI-compatible LLM client**: Works with OpenAI, OpenRouter, vLLM, Ollama, ZAI, OpenCode, and any OpenAI-compatible endpoint.
- **Agent pipeline**: Agents run in parallel waves based on dependencies (Kahn topological sort).
- **Disk caching**: LLM responses cached with 7-day TTL to reduce costs during development.

## Configuration Reference

### config/agents.yaml

The main pipeline configuration file. Key fields:

| Field | Description |
|-------|-------------|
| `schema_name` | Schema to use (default: `datacite-4.6`) |
| `agents` | List of agent definitions |
| `providers` | List of LLM provider connection settings |
| `default_provider` | Provider to use when an agent doesn't specify one |

### Agent Definition

```yaml
- id: core_metadata
  name: Core Metadata Extractor
  description: Extracts basic metadata from resources
  fields: [resource, titles, descriptions, languages, dates]
  prompt: "Your prompt template here..."
  provider: opencode
  model: deepseek-v4-flash
  temperature: 0.2
  depends_on: []
  context_fields: []  # field names to surface from depends_on agents' output
  use_chain_of_thought: true
```

### Provider Definition

```yaml
- name: opencode
  api_key_env: OPENCODE_API_KEY
  base_url: https://opencode.ai/zen/go/v1
  default: true
```

See `config/agents.yaml` and `config/providers.yaml` for full examples.

### Provider defaults: opencode vs. OpenRouter

`config/agents.yaml` on disk pins every agent to `opencode` /
`deepseek-v4-flash` — that's what CI, the test suite, and `gema process`
from the CLI actually run against, so results stay reproducible and cheap
for anyone working on this library. Visor is different: regardless of
whether it finds `config/agents.yaml` directly or seeds a fresh copy for a
frozen build, it rewrites that in-memory (never the file on disk) to
default every agent to OpenRouter's auto-updating DeepSeek V4 Flash alias
instead — a fresh Visor install should never ship an already-stale pinned
checkpoint. See `visor/bootstrap.py::apply_external_user_provider_overrides`
for the exact rule.

## Agents (DataCite 4.6)

The default config defines 5 agents, resolved (via Kahn topological sort
over `depends_on`) into **3 execution waves**, not 1 — agents within a
wave run concurrently; each wave waits for the previous one to finish,
since it needs that wave's merged output:

| Wave | Agent(s) | Depends on | Why |
|------|----------|------------|-----|
| 1 (parallel) | `core_metadata`, `classification`, `media_files` | — | No cross-agent data needed |
| 2 | `creators_publishers` | `core_metadata` | Reuses `core_metadata`'s editor/maintainer/producer names (via `context_fields: [resource]`) instead of re-deriving them, so both agents name the same institution consistently |
| 3 | `rights_funding_citations` | `core_metadata`, `creators_publishers` | Needs `resource` and `publishers` (via `context_fields`) for citation formatting |

| Agent | Fields |
|-------|--------|
| `core_metadata` | resource, titles, descriptions, languages, dates, alternate_identifiers, related_identifiers, geo_locations, temporal_events |
| `creators_publishers` | creators, publishers |
| `classification` | categories, subjects, audiences |
| `rights_funding_citations` | rights, funding_references, citations |
| `media_files` | media_files |

Legacy JSON configurations are preserved at `config/legacy/andrea_v3.json` (5 agents) and `config/legacy/agents_v2.json` (18 agents) for reference.

## Development

```bash
# Run tests (unit + regression, mocked/cache-replay -- no API key needed)
make test

# Golden-output regression only (cache-replay against tests/fixtures/golden/)
make test-regression

# Lint and type check
make lint
make typecheck

# Install in development mode
make install
```

CI (`.github/workflows/ci.yml`) runs the same lint/typecheck/test-library jobs
(plus `visor/`-specific ones) on every PR into `dev` and `main`; `main` PRs also
gate on `visor-build.yml`'s full multi-OS build matrix. CI never runs anything
marked `@pytest.mark.live` (real LLM calls, real cost) -- that stays manual-only.

## Working on Visor

Visor is a separate NiceGUI-based subpackage (`visor/`) with its own test
suite (`make test-visor`). For its architecture, UI structure, building a
frozen installer, and CI details, see [`visor/BUILD.md`](visor/BUILD.md).

## Migration from JSON

If you have existing JSON configurations, use the built-in migration tool:

```bash
uv run python -c "
from metadata_enricher.config.migrate import migrate_json_to_yaml
from pathlib import Path
migrate_json_to_yaml(Path('config/legacy/andrea_v3.json'))
"
```

This generates a YAML file alongside the source JSON, preserving both.

---

## License

AGPL-3.0 -- see [LICENSE](LICENSE)

## Status

v1 -- stable core API. The CLI, config loading, schema registry, agent pipeline, and end-to-end `process` command are all functional.

### Known Limitations

- Only DataCite 4.6 schema is bundled. Custom schemas require implementing the `Schema` Protocol.
- Prompt optimization via DSPy teleprompters is planned but not yet implemented.
