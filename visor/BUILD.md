# Building visor

`visor` is a local-first desktop UI for `metadata-enricher`, so non-programmers
can run the pipeline without touching Python or the CLI. It's a NiceGUI app
(`visor/app.py`) frozen into a standalone installer with PyInstaller — no
Docker, no Python, no `uv` required on the end user's machine.

See `visor/settings.py`'s module docstring and the architecture rule
enforced by `visor/tests/test_architecture.py` before changing how visor
talks to the pipeline: it must always import `metadata_enricher` directly
(the library), never `metadata_enricher.cli`.

## Running from source (development)

```bash
uv sync --extra dev --extra visor --group visor-build
uv run python visor/app.py            # opens a native pywebview window
VISOR_NATIVE=0 uv run python visor/app.py   # serves plain HTTP on :8080 instead
```

First run: no local settings exist yet, so you'll land on **Settings** —
paste whichever API key your `config/agents.yaml`'s default provider needs
(only the providers actually referenced by an agent are asked for, not
every provider merely listed in the config — see
`visor/settings.py::required_env_vars`'s docstring for why that distinction
matters). The key is saved to a local `settings.json` (via `platformdirs`,
OS-appropriate location) — never to `.env` or `config/agents.yaml`.

## Testing

```bash
make test-visor
```

Runs `visor/tests/` — settings roundtrip, form/paste/upload → temp file →
`FilesystemInputSource` glue, the bootstrap/config-seeding logic, and the
CLI-import-boundary architecture guard. Kept separate from `make test`
(the library's own suite/coverage number) on purpose.

## Building a frozen bundle

```bash
make install-visor   # uv sync --extra visor --group visor-build
make build-visor      # uv run pyinstaller visor/visor.spec --noconfirm
```

Produces a **onedir** bundle at `dist/Visor/` (Linux/Windows) or
`dist/Visor.app` (macOS) — not onefile; see `visor/visor.spec`'s docstring
for why (startup speed, AV/SmartScreen scan surface, transparency for
support). Always run PyInstaller through `uv run`, never a globally
pip-installed one, so frozen deps match `uv.lock`.

**Cross-compilation is not possible** — PyInstaller only builds for the OS
it's running on. A Windows `.exe`/installer can only be produced on
Windows; a macOS `.app`/`.dmg` only on macOS. This is why CI (below) uses
both a `windows-latest` and a `macos-latest` runner rather than one machine
producing both.

### Windows installer

After `make build-visor` on Windows, compile `visor/installer/windows.iss`
with Inno Setup (`iscc visor/installer/windows.iss`, or the GUI) — produces
`dist_installer/Visor-Setup.exe`: a normal double-click installer with a
Start Menu entry and uninstaller.

Native-window mode (`ui.run(native=True)`, visor's default) needs the Edge
WebView2 runtime, present by default on Windows 10 21H2+/11 but **not
guaranteed on older Windows 10** — a real prerequisite PyInstaller doesn't
solve. If a user's machine lacks it, `VISOR_NATIVE=0` (serving a plain
browser tab instead of a native window) is the fallback.

### macOS installer

After `make build-visor` on macOS, run:

```bash
bash visor/installer/macos_build_dmg.sh
```

Produces `dist/Visor.dmg` via `hdiutil` (built into every Mac, no extra
dependency) from the `.app` bundle. `visor/visor.spec` explicitly adds a
`BUNDLE()` step (guarded by `sys.platform == "darwin"`) — a plain PyInstaller
`COLLECT` alone produces just a folder on macOS too, not a real
double-clickable `.app`.

### CI (GitHub Actions)

`.github/workflows/visor-build.yml` builds both installers on
`windows-latest`/`macos-latest`, triggered manually (`workflow_dispatch`) or
on push to the `visor` branch touching `visor/`, the library, or the config.
It runs `make test-visor`-equivalent, then the same PyInstaller +
Inno-Setup/`hdiutil` steps above, and uploads both installers as workflow
artifacts. This is scoped entirely to visor — it does not change the core
library's existing "no CI/CD, all checks via Makefile" convention.

**Honest limitation of how this was built**: authored and validated from a
Linux sandbox. What was actually verified here:
- A real Linux onedir PyInstaller build from `visor.spec` (confirmed working,
  ~223MB, matches the size estimate below).
- The frozen binary actually boots and serves the app over HTTP — including
  the first-run config-seeding path (`visor/bootstrap.py`), verified by
  running the frozen exe from a directory outside the repo with a fake
  `$HOME` and no config anywhere, and confirming it correctly copied the
  bundled default into `~/.config/metagen/agents.yaml`.
- The `visor-build.yml` YAML is syntactically valid and its logic was
  reasoned through carefully, but it has **not** actually been run on a
  real `windows-latest`/`macos-latest` GitHub Actions runner. The Windows
  `.exe`/installer and the macOS `.dmg` have never actually been produced or
  opened by this work. That first real CI run (or a manual build on those
  OSes) is the actual proof this pipeline works end to end — treat it as
  the next concrete verification step, not a formality.

## Known limitations (not solved here, by design)

- **Bundle size**: ~150-300MB per OS (NiceGUI's Vue/Quasar assets, FastAPI/
  Uvicorn, openai/instructor/httpx/pydantic-core, pywebview). Confirmed
  ~223MB on the Linux build.
- **Unsigned binaries**: Windows SmartScreen is dismissable by the user.
  macOS Gatekeeper effectively blocks a non-programmer unless the app is
  notarized ($99/yr Apple Developer Program) or they know to right-click →
  Open. This is the bigger of the two adoption blockers and is a real,
  separate decision — not addressed by this build setup.
- **Batch/folder processing** is not in the UI yet (single resource at a
  time) — an intentional fast-follow, see the visor plan doc.
