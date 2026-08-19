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
uv run python -m visor.app
```

Must be `-m visor.app`, not `python visor\app.py` / `python visor/app.py` —
`app.py` does absolute imports (`from visor.bootstrap import ...`), and
running it as a bare script path only puts `visor/` itself on `sys.path`,
not the repo root, so `import visor` fails with `ModuleNotFoundError: No
module named 'visor'`. `-m` runs it from the repo root as a package member
instead, which resolves correctly. This bites on every OS, not just
Windows — confirmed by actually hitting it from WSL.

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

See the root [README](../README.md#visor-desktop-app) for the basic
`uv sync` / `uv run python -m visor.app` commands — this section only
covers WSL-specific nuance not needed by an end user.

**Under WSL specifically**: native mode fails —
`webview.errors.WebViewException: You must have either QT or GTK with
Python extensions installed` — WSL ships neither GUI toolkit by default,
so `pywebview` can't open a window. Always use `VISOR_NATIVE=0` under WSL.
It serves plain HTTP; from Windows, open a browser to whatever host/port
it prints (`http://127.0.0.1:<port>` — WSL2 forwards this into Windows
automatically on current builds; if that doesn't resolve, run
`ip addr show eth0 | grep 'inet '` inside WSL and use that IP instead).
This gets real app code and a real click flow, just NiceGUI's browser
rendering instead of pywebview's native window — it won't catch
native-window-specific issues (WebView2 presence on Windows, native window
chrome). For those, run the Windows quick-start above from PowerShell
directly, not WSL.

## UI structure — Settings / Agents / Run tabs

Three tabs, always visible and freely clickable at any time — not a locked
wizard. `ui.tab_panels`' default `keep_alive=True` means switching tabs
never destroys another tab's state (e.g. a run stays live in the Run tab
while you flip over to Settings and back).

- **Settings** — one API key input per *declared* provider (not just
  providers an agent currently uses — see below), each captioned with
  which agent IDs currently use it, or "not currently used by any agent"
  if none do. Saved to a local `settings.json` (via `platformdirs`,
  OS-appropriate location) — never to `.env` or `config/agents.yaml`.
  Saving auto-switches you to the Run tab. No "default provider" selector
  here — `PipelineConfig.default_provider` never actually chose which
  provider an agent runs with (each `AgentConfig.provider`, set in the
  Agents tab, is authoritative; `default_provider` is only ever read for
  a CLI display label) — keeping both in the UI implied a control that
  didn't exist, so it's gone. `visor/settings.py::required_env_vars`
  (only providers actually referenced by an agent) still gates the
  Run tab; the broader `all_provider_env_vars` (every declared provider)
  is what Settings displays — deliberately different scopes for
  deliberately different jobs.
- **Agents** (`visor/pages/agents_page.py`) — each pipeline agent's
  `provider`, `model`, and `temperature` as visible, editable fields
  (previously none of these were exposed in the UI). `provider` is a
  select populated from `pipeline_config.providers` — always a valid
  choice by construction. `model` is a free-text input, not a dropdown —
  there's no enumerable "known models per provider" list anywhere in this
  project's config (`config/providers.yaml` only has connection
  settings), so a fabricated model list would go stale and could imply
  only listed models work. Everything else (prompt, fields, depends_on)
  is read-only in a collapsed "Advanced" section for transparency.
  Download/Upload buttons round-trip the *entire* `PipelineConfig` as
  JSON — Upload re-validates through the model's own cross-reference
  validators before applying anything, so a bad file never leaves a
  half-applied config. Edits are session-only (mutate the shared
  `PipelineConfig` object in place) — never written back to
  `config/agents.yaml`; download the JSON to keep changes for next time.
- **Run** (`visor/pages/run_page.py`) — one tab, three in-place phases
  (never a separate "Result" tab — a disabled second tab is confusing for
  a non-technical user, and this keeps the causal link between "I pressed
  Run" and "the answer appeared" visible in one place):
  1. *Form* — fill-a-form / paste-JSON (with a collapsed "what should
     this look like?" example) / upload-a-file, same as before.
  2. *Running* — a live log console (`ui.log`, fixed height, auto-scrolls)
     fed by a `logging.Handler` on the `metadata_enricher` logger
     namespace. `Pipeline.run()` executes on a background thread via
     `run.io_bound`; the handler puts formatted records on a thread-safe
     `queue.Queue` (`visor/log_stream.py`), and a `ui.timer` on the UI's
     own event loop drains it every 0.3s — never touching a NiceGUI
     element directly from the worker thread. `agents/base.py` now logs a
     start/finish line per agent (with elapsed time and token count) —
     previously only wave-level progress was logged, which made the
     console look stuck for the entire run with no sense of progress.
     A collapsed "Submitted input" panel shows exactly what was sent, so
     it isn't lost once the form is out of view.
  3. *Result* — Download/"Run another" buttons pinned above a fixed-height
     `ui.scroll_area` holding the JSON (or the error, on failure); a
     token-usage line ("N in / M out, T total") when the pipeline reports
     any; a "Models used" list (agent id -> resolved model, see below) when
     any agent's call reported one; the "Submitted input" panel carries
     over from the running phase; the log collapses into a "Show details
     (N lines)" expander, auto-expanded on failure since that's exactly
     when it's the answer.

These three decisions (in-place phases vs. a separate Result tab, cards+download/upload vs. a raw JSON editor for Agents, and confirming the fixed-height-scroll-with-pinned-actions pattern) were run past an Opus-level design consult before building, given a non-technical audience — see the commit history for the full rationale.

### Token usage / cost estimation

`TokenUsage` (`types.py`) already existed but every call site hardcoded
zeros — nothing actually asked the LLM client for real usage. Fixed by
adding `complete_with_usage()` as an **optional, duck-typed** extension
(not part of the formal `LLMClient` Protocol) implemented by the real
production chain (`InstructorLLMClient` via instructor's
`create_with_completion()`, `RetryableLLMClient`, `CachedLLMClient`) —
`agents/base.py` calls it via `hasattr` and falls back to plain
`complete()` + zero usage for any mock/fake lacking it, so every existing
test file's own Protocol-compliant mock keeps working completely
unchanged. `pipeline.py::_aggregate_token_usage` sums real usage once per
underlying LLM call (dedup by `TokenUsage` object identity — one agent
call produces one `TokenUsage` shared across N `AgentResult`s, one per
output field; summing naively would multiply that agent's cost by its
field count) into `PipelineResult.token_usage`, surfaced in visor's
Result phase. A cache hit reports zero new usage (nothing was actually
called) — the number shown is "cost of running this now," not "value of
the data." Cache entries written before this existed are read as legacy
bare-shape values (no usage recorded) rather than breaking — confirmed
directly against the real committed `tests/fixtures/golden/cache/cache.db`.

### Resolved model per agent

`TokenUsage.model` carries the provider's own resolved model id for that
call (`completion.model` from the OpenAI-compatible response) — needed
because a configured model can be an auto-updating alias (e.g.
OpenRouter's `~deepseek/deepseek-v4-flash-latest`, see
`bootstrap.py::apply_external_user_provider_overrides`), and the alias
name alone doesn't tell you which concrete checkpoint actually served the
request. `pipeline.py::_build_models_used` maps agent id -> resolved model
(skipping any agent whose call reported none — a mock/fake client or a
cache hit, same as token usage) into `PipelineResult.models_used`,
surfaced as visor's Result-phase "Models used" list. Empty entirely means
nothing to show, not an error.

## Testing

```bash
make test-visor
```

Runs `visor/tests/` — settings roundtrip, form/paste/upload → temp file →
`FilesystemInputSource` glue, the bootstrap/config-seeding logic, the
CLI-import-boundary architecture guard, `log_stream.py`'s capture/drain/
level-restore logic (pure stdlib, no UI needed), and click-through UI
tests (`test_ui_navigation.py`, via `nicegui.testing.User`) covering tab
switching and the Agents tab's download-reflects-an-edit round trip — no
real LLM call in any of these, so no API key needed. Kept separate from
`make test` (the library's own suite/coverage number) on purpose. Always
passes `-m "not live"` — deterministically, not just "skip if no key is
found": a real key showed up in `os.environ` inside a test run here even
when a separate check in the same shell moments earlier showed none, so
skip-by-absence alone isn't a trustworthy cost guard in every environment.

**Known gap, stated plainly**: the Agents tab's *Upload* path (parse +
validate + apply) has no dedicated test — NiceGUI's test harness has no
built-in helper for simulating a file upload (unlike `ui.download`, which
`user.download.next()` supports directly), and building a full mocked
5-agent pipeline run through the real production `config/agents.yaml` to
exercise upload-then-run needs response models matching all five agents'
`fields`, which wasn't worth the complexity for this pass. The actual
parse/validate logic is two lines of stdlib `json.loads` + pydantic's own
`PipelineConfig(**data)` — already covered by the library's own config
model tests — so the residual risk is narrow, but it's a real gap, not a
silent one.

```bash
make test-visor-live
```

Runs `visor/tests/test_app_e2e.py` — a real click-through of the whole app
using NiceGUI's in-process user-simulation harness (`nicegui.testing.User`):
opens the page (lands on Run, sees the "add an API key" gate since none is
set), switches to the Settings tab, fills it, saves (auto-switches back to
Run), fills the Run form, clicks Run (a real multi-agent LLM call, live log
console visible while it runs), waits for Result, clicks Download, and
asserts the exact bytes handed to `ui.download`. No browser, but real app code and
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
  same first-run config-seeding into `~/.config/gema/agents.yaml`
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

### CI (GitHub Actions) — branch strategy

Two workflows, gating two different tiers of the branch flow:

```
feature/* branches --PR--> dev --PR--> main
                     (ci.yml)     (ci.yml + visor-build.yml)
```

- **`.github/workflows/ci.yml`** — cheap checks: lint, mypy, the library's
  own test suite, and `make test-visor`. Single OS (`ubuntu-latest`), no
  installer build, nothing marked `live` (no real LLM calls, no cost).
  Runs on every PR into `dev` or `main`, and on direct pushes to `dev`.
  This is the "partial/functional" tier — fast feedback for day-to-day
  work landing on `dev`.
- **`.github/workflows/visor-build.yml`** — the expensive tier: builds
  both installers **and** both portable executables on
  `windows-latest`/`macos-latest`. Runs `make test-visor`, then the same
  PyInstaller + Inno-Setup/`hdiutil` steps above, uploading four artifacts
  per run: `visor-windows-installer`, `visor-windows-portable`,
  `visor-macos-dmg`, `visor-macos-portable`. Triggered only on a PR
  targeting `main` (i.e. the `dev` -> `main` promotion) or manually via
  `workflow_dispatch` — deliberately **not** on every push to a feature
  branch, since a real multi-OS PyInstaller + installer build is slow and
  not worth running on work that hasn't passed the cheap tier yet.

`main` is branch-protected: PRs required, direct pushes blocked, and both
workflows' checks must pass before a merge is allowed. `dev` is
intentionally lighter (no protection rule) — it's the fast-moving
integration branch; `main` is the one that must always be in a shippable
state. This is scoped entirely to visor — it does not change the core
library's existing "no CI/CD, all checks via Makefile" convention for
day-to-day local development.

**Honest limitation of how this was built**: authored and validated from a
Linux sandbox. What was actually verified here:
- A real Linux onedir PyInstaller build from `visor.spec` (confirmed working,
  ~223MB, matches the size estimate below).
- The frozen binary actually boots and serves the app over HTTP — including
  the first-run config-seeding path (`visor/bootstrap.py`), verified by
  running the frozen exe from a directory outside the repo with a fake
  `$HOME` and no config anywhere, and confirming it correctly copied the
  bundled default into `~/.config/gema/agents.yaml`.
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
