# Metadata Enricher (metagen)

Automatic metadata generation for scholarly resources using LLM agents.

## Quickstart

### Prerequisites

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
git clone <repo-url>
cd proj-metadata-agents
uv sync --extra dev
```

### Configuration

1. Copy `.env.example` to `.env` and fill in your API keys:

   ```bash
   cp .env.example .env
   # Edit .env with your OPENAI_API_KEY, ZAI_API_KEY, or OPENCODE_API_KEY
   ```

2. The default config is at `config/agents.yaml` (5 agents for DataCite 4.6 metadata).
   Provider connection settings are defined in `config/providers.yaml`.

### Usage

```bash
# List available schemas
uv run metagen list-schemas

# List providers from config
uv run metagen list-providers --config config/agents.yaml

# Validate an input file
uv run metagen validate examples/sample_input01.json

# Process a resource (requires API key)
uv run metagen process examples/sample_input01.json --config config/agents.yaml --output output.json
```

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

## Agents (DataCite 4.6)

The default config defines 5 agents running sequentially on a dependency chain:

| Agent | Fields | Dependencies |
|-------|--------|-------------|
| `core_metadata` | resource, titles, descriptions, languages, dates, alt IDs, related IDs, temporal/geo | -- |
| `creators_publishers` | creators, publishers | core_metadata |
| `classification` | categories, subjects, audiences | creators_publishers |
| `rights_funding_citations` | rights, funding_references, citations | classification |
| `media_files` | media_files | rights_funding_citations |

Legacy JSON configurations are preserved at `config/andrea_v3.json` (5 agents) and `config/agents_v2.json` (18 agents) for reference.

## Development

```bash
# Run tests
make test

# Lint and type check
make lint
make typecheck

# Install in development mode
make install
```

## Migration from JSON

If you have existing JSON configurations, use the built-in migration tool:

```bash
uv run python -c "
from metadata_enricher.config.migrate import migrate_json_to_yaml
from pathlib import Path
migrate_json_to_yaml(Path('config/andrea_v3.json'))
"
```

This generates a YAML file alongside the source JSON, preserving both.

## License

MIT -- see [LICENSE](LICENSE)

## Status

v1 -- stable core API. The CLI, config loading, schema registry, agent pipeline, and end-to-end `process` command are all functional.

### Known Limitations

- Only DataCite 4.6 schema is bundled. Custom schemas require implementing the `Schema` Protocol.
- Prompt optimization via DSPy teleprompters is planned but not yet implemented.
