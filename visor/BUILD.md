# Building visor

`visor` is a local-first desktop UI for `metadata-enricher`, so non-programmers
can run the pipeline without touching Python or the CLI. It's a NiceGUI app
(`visor/app.py`) frozen into a standalone installer with PyInstaller — no
Docker, no Python, no `uv` required on the end user's machine.

See `visor/settings.py`'s module docstring and the architecture rule
enforced by `visor/tests/test_architecture.py` before changing how visor
talks to the pipeline: it must always import `metadata_enricher` directly
(the library), never `metadata_enricher.cli`.

## Windows quick start (from a WSL machine or otherwise)

WSL runs a Linux kernel — anything built inside WSL is a Linux binary, never
a Windows `.exe`. To actually test Windows (native window, WebView2, a real
installer), run these steps from **Windows PowerShell directly**, not the
WSL bash shell.

```powershell
# 1. Install uv (Windows-native, one-time)
irm https://astral.sh/uv/install.ps1 | iex

# 2. Get the repo onto the Windows filesystem — clone fresh, don't work
#    off \\wsl$\... (slow, and uv/PyInstaller can choke on cross-FS locking)
cd C:\dev
git clone <repo-url> proj-metadata-agents
cd proj-metadata-agents
git checkout visor

# 3. Install deps and smoke-test unfrozen (fastest way to check WebView2 etc.)
uv sync --extra dev --extra visor --group visor-build
uv run python visor\app.py
```

That last command opens a real pywebview native window on Windows — the one
thing the Linux sandbox this project was built in cannot verify at all.

To build the actual installer (matches what CI produces):

```powershell
uv run pyinstaller visor\visor.spec --noconfirm
choco install innosetup          # or download from jrsoftware.org
iscc visor\installer\windows.iss
```

Produces `dist_installer\Visor-Setup.exe` — double-click it like a real user.

To run the test suite the same way CI does:

```powershell
make test-visor        # Windows GitHub runners ship GNU Make; if your local
                        # machine doesn't, run the pytest command make wraps
                        # directly — see the Makefile target for the exact flags
```

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
(the library's own suite/coverage number) on purpose. Always passes
`-m "not live"` — deterministically, not just "skip if no key is found":
a real key showed up in `os.environ` inside a test run here even when a
separate check in the same shell moments earlier showed none, so
skip-by-absence alone isn't a trustworthy cost guard in every environment.

```bash
make test-visor-live
```

Runs `visor/tests/test_app_e2e.py` — a real click-through of the whole app
using NiceGUI's in-process user-simulation harness (`nicegui.testing.User`):
opens the page, fills Settings, saves, fills the Run form, clicks Run (a
real multi-agent LLM call), waits for Result, clicks Download, and asserts
the exact bytes handed to `ui.download`. No browser, but real app code and
real click handlers — the strongest test in this suite. Caught two real
bugs during development: NiceGUI's test-simulation `Download.content()`
doesn't do the str→bytes conversion the real implementation does (fixed by
always encoding to bytes before calling it — correct in both paths), and
`run_page.py`'s cleanup touched an already-deleted button after the result
screen replaced it (harmless in practice, fixed anyway).

## Building a frozen bundle

```bash
make install-visor   # uv sync --extra visor --group visor-build
make build-visor      # uv run pyinstaller visor/visor.spec --noconfirm
```

Produces **two** targets from one spec, in one PyInstaller run:

- `dist/Visor/` (onedir, Linux/Windows) / `dist/Visor.app` (macOS) —
  the primary target, fed into the installers below. Fast startup, no
  extraction step per launch — see `visor/visor.spec`'s docstring for
  the full rationale (AV/SmartScreen scan surface, support
  transparency).
- `dist/Visor-portable.exe` (Windows) / `dist/Visor-portable` (macOS/
  Linux) — a single-file, no-install-step executable. Useful for
  locked-down machines without admin rights to run an installer.
  Measured on the Linux build: **76MB vs 223MB** for onedir — smaller
  on disk (the onefile archive is zlib-compressed as a whole), but
  self-extracts to a fresh temp dir on *every* launch, so it's slower
  to start than onedir. Verified booting headless on Linux (HTTP 200,
  same first-run config-seeding into `~/.config/metagen/agents.yaml`
  as the onedir build) — not yet verified as a real double-click on
  Windows/macOS.

Always run PyInstaller through `uv run`, never a globally pip-installed
one, so frozen deps match `uv.lock`.

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

`.github/workflows/visor-build.yml` builds both installers **and** both
portable executables on `windows-latest`/`macos-latest`, triggered manually
(`workflow_dispatch`) or on push to the `visor` branch touching `visor/`,
the library, or the config. It runs `make test-visor`, then the same
PyInstaller + Inno-Setup/`hdiutil` steps above, and uploads four artifacts
per run: `visor-windows-installer`, `visor-windows-portable`,
`visor-macos-dmg`, `visor-macos-portable`. This is scoped entirely to
visor — it does not change the core library's existing "no CI/CD, all
checks via Makefile" convention.

**Honest limitation of how this was built**: authored and validated from a
Linux sandbox. What was actually verified here:
- A real Linux onedir PyInstaller build from `visor.spec` (confirmed working,
  ~223MB, matches the size estimate below).
- The frozen binary actually boots and serves the app over HTTP — including
  the first-run config-seeding path (`visor/bootstrap.py`), verified by
  running the frozen exe from a directory outside the repo with a fake
  `$HOME` and no config anywhere, and confirming it correctly copied the
  bundled default into `~/.config/metagen/agents.yaml`.
- The `visor-build.yml` workflow has now run on a real `windows-latest`
  runner. First run caught a real bug: the test step called
  `uv run pytest visor/tests -v` directly instead of `make test-visor`,
  so it ran without `-p nicegui.testing.user_plugin -o asyncio_mode=auto
  -m "not live"` — the `user` fixture wasn't registered and
  `test_app_e2e.py` errored (`fixture 'user' not found`) instead of being
  deselected. Fixed by pointing the workflow at `make test-visor` so CI
  and local runs share one flag set instead of two that can drift apart.
  Still not yet verified: a full green run producing the actual Windows
  `.exe`/installer artifact, and any macOS run at all.

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
