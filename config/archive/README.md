# Archived config artifacts

These files have zero references anywhere in the codebase, tests, or docs —
confirmed via grep and `vulture` before moving them here. They're kept only
as a backup (not part of any active config search path, migration example,
or test fixture); nothing reads them.

| File | Why it's here |
|------|---------------|
| `andrea.json` | Orphaned legacy config; superseded, never referenced |
| `andrea_v3.yaml` | Stale generated migration output, not referenced |
| `providers.json` | Orphaned sibling providers file; its counterpart JSON moved to `config/legacy/` without it |
| `agents.json` | Orphaned legacy config; superseded by `config/legacy/agents_v2.json` |
| `andrea_v2.json` | Orphaned legacy config; superseded by `config/legacy/andrea_v3.json` |

For legacy configs that ARE still referenced (by README.md, CLAUDE.md, docs,
and `test_config_migration.py` as migration examples), see `config/legacy/`
instead — `agents_v2.json` and `andrea_v3.json`.
