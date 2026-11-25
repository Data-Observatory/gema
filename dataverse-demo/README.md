# Dataverse demo stack

A local, disposable Dataverse instance for the live exercise: attendees fill
in a resource description, run it through `gema`/visor to get
CDIF JSON-LD, convert that to Dataverse's native JSON (gema's Dataverse
exporter — see below), and upload the resulting dataset to *this* instance so
everyone can see how it renders.

This is `compose.yml` from IQSS's own official demo/evaluation setup,
essentially unmodified — see the top of that file for the exact two
deviations (the "demo" persona pre-selected instead of "dev", and the
blocked-API key made configurable via `.env` instead of hardcoded). Source:
[IQSS/dataverse — Demo or Evaluation](https://guides.dataverse.org/en/6.2/container/running/demo.html).

## Quick start

Everything below in one pass — base Dataverse stack, the upload proxy wired
with a real token, Caddy fanning out one port, and visor for `/meta`. Each
step is explained in detail further down; this is just the commands.

```bash
cd dataverse-demo
cp .env.example .env
# edit .env: at minimum change BLOCKED_API_KEY to something only you know

docker compose up -d
# first boot takes a few minutes — watch for `bootstrap` exiting with
# "Done, your instance has been configured for demo or eval."
docker logs -f bootstrap

# wire the uploader's Dataverse API token — bootstrap already generated one
./scripts/get_admin_token.sh
# paste the printed token into .env as DATAVERSE_API_TOKEN, then:
docker compose up -d --force-recreate uploader caddy
```

In a separate terminal, run visor for the `/meta` route (not a container —
see "Caddy" below for why `VISOR_ROOT_PATH` is required, not optional):

```bash
VISOR_NATIVE=0 VISOR_PORT=8001 VISOR_ROOT_PATH=/meta uv run python -m visor.app
```

Everything through Caddy on one port (default 8000, `CADDY_PORT` in `.env`):

- **http://localhost:8000/** — Dataverse UI (`dataverseAdmin` / `admin1`)
- **http://localhost:8000/up/** — upload form for attendees
- **http://localhost:8000/meta/** — visor
- **http://localhost:8000/intake/** — workshop intake page (admin: `/intake/admin/`, see
  "Intake page" below)

(Or hit each service directly without Caddy: 8080 / 8090 / 8001 / 8095.)

Sharing this beyond localhost (Tailscale, Funnel), resetting between runs,
and the CDIF → Dataverse translator are all covered in detail below.

## Requirements

- Docker (the official guide calls Windows support "experimental" — Mac/Linux
  are the tested platforms)
- ~8GB RAM free, since this boots Postgres + Solr + Payara + a mail catcher
  + two previewer-registration containers all at once

**Verified working end-to-end** (2026-08-05, this repo's dev sandbox, once
Docker Desktop's WSL integration was enabled): a real `docker compose up`
boot, bootstrap completing cleanly, and the full API smoke test below run
live against the resulting instance — collection created, dataset created,
file uploaded, both published, confirmed via `GET /api/datasets/:persistentId`
showing `"locks": []`. Two real problems were hit and fixed along the way,
neither specific to this compose file:
- The Docker VM's disk was completely full from unrelated projects' images
  — `docker image prune` (dangling images) + `docker builder prune` (build
  cache) freed enough space; nothing tagged or in-use was touched.
- A leftover process from unrelated earlier work was still bound to host
  port 8080, so Docker's `dataverse:8080` port mapping silently failed to
  bind — freeing the port and `docker compose up -d --force-recreate
  dataverse` fixed it. If `http://localhost:8080` doesn't respond after a
  clean boot, check `docker port dataverse` actually lists `8080` and
  `ss -tlnp | grep 8080` to see what's really holding the port.

## API smoke test (no browser)

```bash
cd dataverse-demo/scripts
API_TOKEN=$(./get_admin_token.sh)
API_TOKEN="$API_TOKEN" ./smoke_test.sh
```

`smoke_test.sh` runs the exact sequence the official guide's manual smoke
test describes — publish root, create a collection, create a dataset,
upload a file, publish the collection, publish the dataset — entirely via
`curl`, using `example_collection.json`/`example_dataset.json` as
known-good payloads. Every command in it was run live against a real
instance before being committed (see native-api.rst in IQSS/dataverse for
the source of each one), not copied from memory. `get_admin_token.sh`
recovers the token bootstrap already generated from its container logs —
see that script's docstring for why (and the fallback) if it comes up empty.

Override `COLLECTION_ALIAS` (env var) to run it more than once against the
same instance — collection aliases must be unique, so re-running with the
default alias against an already-populated instance fails at step 2 with
a clear "such a collection already exists" error, not a bug.

This never needed the CDIF → Dataverse translator to prove the API
mechanism works — that's `example_dataset.json`'s whole point, a small
hand-written payload. To use the real translator
(`metadata_enricher.exporters.dataverse`) instead, run
`scripts/export_from_metadata_enricher.py` to generate a real one from an
actual gema output instead:

```bash
cd /path/to/repo/root   # needs metadata_enricher importable
uv run python dataverse-demo/scripts/export_from_metadata_enricher.py \
  tests/fixtures/golden/expected/sample_input01.json \
  --output dataverse-demo/scripts/example_dataset.json
```

Verified live: this exact command's output was POSTed to a real running
instance and accepted (`{"status":"OK",...}`), producing a real dataset
with the correct title/author pulled straight from actual gema
output — not a synthetic example. Without `--classify`, Subject defaults
to `"Other"` (no LLM call, no cost); add `--classify` to run the real
classification call (needs the provider's API key set, same as running
gema itself). Either way it prints any warnings — e.g. no
contact email found anywhere in the source metadata, a real gap between
the source metadata and Dataverse's required fields, not a bug — so check those
before publishing.

## Upload proxy (for attendees without API tooling)

`uploader/` is a very light FastAPI service — one form, no auth of its own,
no database — that takes a Dataverse-native JSON payload (paste or file
upload) and forwards it to this instance's native API
(`POST /api/dataverses/:alias/datasets`), the same call `scripts/smoke_test.sh`
makes by hand. It's for attendees who have gema/visor output
but no `curl`/API-token workflow of their own.

It's part of `compose.yml` (service `uploader`, port 8090) so it comes up
with everything else. Set `DATAVERSE_API_TOKEN` in `.env` first — see
`.env.example` — otherwise the form loads but every submission fails with
a clear "no token configured" error rather than a silent 401. Visit
**http://localhost:8080** on the Dataverse side stays the admin/API story;
**http://localhost:8090** is the plain form attendees actually use.

Datasets are created as drafts unless the "Publish immediately" checkbox
is ticked — leave it unticked if you want to review before making
attendees' uploads publicly visible.

This has the exact same secret-exposure shape as the section below: anyone
who can reach port 8090 can create datasets in `DATAVERSE_COLLECTION_ALIAS`
using the token baked into the container's environment. Scope Tailscale
ACLs the same way, and use a token scoped to a non-admin account if you
don't want attendees' traffic able to do anything an admin token can do.

## Intake page (live workshop flow)

`intake/` is a small server-rendered FastAPI app (service `intake` in `compose.yml`, route
`/intake/` in Caddy) for running the workshop without Visor or any attendee tooling:
attendees submit a URL, the admin curates the list, and **one click** runs GEMA! on every
pending resource (library call, no GUI) and publishes each result to this Dataverse.

### Setup

1. In `.env` (see `.env.example`) set at least:

   | Key | Purpose |
   |---|---|
   | `INTAKE_ADMIN_TOKEN` | admin login for `/intake/admin/` (`openssl rand -hex 24`); the container refuses to start without it |
   | `OPENCODE_API_KEY` | GEMA! runs on the `opencode` provider (production model from `config/agents.yaml`, `deepseek-v4.1-flash`); the container refuses to start without it |
   | `DATAVERSE_API_TOKEN` | same token the uploader uses (`./scripts/get_admin_token.sh`); without it the pages work but **Process** is disabled |
   | `DATAVERSE_COLLECTION_ALIAS` | collection the datasets are created in; it must already be *published* (`root` always is) |
   | `INTAKE_DEFAULT_CONTACT_EMAIL` / `_NAME` | Dataverse requires a contact; used when the page exposes none |
   | `INTAKE_WORKERS` (4), `INTAKE_RECORD_TIMEOUT` (300 s), `INTAKE_MAX_RECORDS` (40), `INTAKE_RATE_LIMIT` (5 submissions/IP/min) | knobs, all optional |

2. `docker compose up -d --build intake caddy` (the image is built from the **repo root**,
   it installs the `gema` library from `src/` and reuses `config/`). Data (SQLite file and
   `intake.log`) lives on the `intake_data` volume at `/data`.
3. Open `http://localhost:8000/intake/` (or the Tailscale Funnel URL + `/intake/`).
   For local debugging the container is also on `http://127.0.0.1:8095/`.

Running outside Docker: from the repo root,
`INTAKE_ADMIN_TOKEN=... OPENCODE_API_KEY=... INTAKE_DATA_DIR=./intake-data
INTAKE_GEMA_CONFIG=config/agents.yaml INTAKE_EXPORT_CONFIG=config/dataverse_export.yaml
PYTHONPATH=dataverse-demo/intake uv run --with fastapi --with python-multipart --with jinja2
--with uvicorn uvicorn --factory intake_app.main:build_app --port 8095`.

### Workshop flow

1. **Before**: stack up, token and keys in `.env`, try one submission end to end.
2. **During**: attendees open `/intake/`, add *URL* + optional *hints* + a *pseudonym*. The
   list refreshes every 10 s; a duplicate URL is refused naming who submitted it first. The
   pseudonym is stored only as the Dataverse keyword `group:<pseudonym>`, never as author or
   publisher. *Hints* are passed to GEMA! as `context_hints`, the library's existing
   mechanism for externally supplied facts (the agents treat it as trusted context).
3. **Admin** (`/intake/admin/`, token login): delete junk rows (only `pending`/`failed`),
   **Close intake** when submissions should stop, then **Process pending**. Records run in
   parallel (`INTAKE_WORKERS`); each is checked for reachability, run through GEMA!,
   converted with `metadata_enricher.exporters.dataverse`, created in the collection and
   published, and its PID is stored as soon as the dataset exists. A dead URL or any error
   marks only that record `failed` with a short reason (shown to the admin, not on the public
   page); one automatic retry covers network errors, HTTP 5xx and rate limits. **Retry
   failed** re-runs only failed rows (an already-created dataset is only published, never
   duplicated); `done` rows are never touched again. **Export results CSV** gives the table.
4. Attendees' rows turn `done` with a *View in Dataverse* link.

Restarting the container mid-batch is safe: rows left `processing` go back to `pending`.
Run tests (no network, no LLM, no Dataverse), from the repo root:

```bash
uv run --with fastapi --with python-multipart --with jinja2 pytest dataverse-demo/intake/tests
```

The page fetches attendee-submitted URLs from the server, so it refuses non-public
addresses (IP literals, `localhost`, single-label names) at submit time and re-checks DNS
and every redirect hop right before fetching. Treat the admin token like the Dataverse
token: anyone holding it can publish to the instance.

## Caddy (single entrypoint for Tailscale)

If you're sharing this over Tailscale (below) and don't want to open/remember
three separate ports, `caddy` (service in `compose.yml`, `Caddyfile` at the
repo root of this folder) fans out one port to path-based routes:

- **`/intake`** → the workshop intake page (see above). Caddy sets `X-Real-IP` from its
  own `{client_ip}` (global `trusted_proxies` = private ranges only), which the intake's
  per-IP rate limit uses. Not verified live behind Tailscale Funnel.
- **`/up`** → the uploader form. Works fully — confirmed live, including a
  real dataset upload through the proxy.
- **`/meta`** → visor's own hosted mode, running on your host machine (not
  a container — start it with `VISOR_NATIVE=0 VISOR_PORT=8001
  VISOR_ROOT_PATH=/meta python -m visor.app`; `VISOR_ROOT_PATH` is required,
  not optional — see `.env.example`). Works fully — confirmed live, assets
  *and* the socket.io websocket handshake all correctly prefixed.
- **everything else** falls through to Dataverse at the root — deliberate,
  not a fallback for lack of trying: Dataverse (JSF/Payara) emits
  root-relative links throughout and Payara's context-root is fixed at WAR
  deployment time, so it can't live under a subpath at all (confirmed live
  earlier — a `/catalogo/*` attempt 302'd to a root-relative
  `/loginpage.xhtml` with no prefix and 404'd). Keeping it at the root
  sidesteps that entirely, since no path-stripping/rewriting happens for it.

Default port is 8000 (`CADDY_PORT` in `.env`). `docker compose up -d caddy`
brings it up alongside everything else.

**Changing the port**: set `CADDY_PORT` in `.env` (e.g. `CADDY_PORT=8123`)
and recreate the container — `Caddyfile` itself has no hardcoded host port
(`:80` in there is container-internal, never exposed directly), so this env
var is the single control point. All three routes move together since
they're all paths under that one port, not separate ports:

```bash
docker compose up -d --force-recreate caddy
```

**`VISOR_ROOT_PATH` is not optional — a real trap if forgotten.** If you
start visor without it and load `/meta`, the page loads but shows
*"Your browser does not support ES modules. Please use a modern browser."*
— this is misleading, it's not actually a browser problem. Without
`VISOR_ROOT_PATH`, visor emits its JS module URLs as `/_nicegui/...`
instead of `/meta/_nicegui/...`; Caddy's `/meta/*` route never sees a bare
`/_nicegui/...` request, so it 404s, the `<script type="module">` tag
silently fails to load, and the browser falls back to that static warning
text. Confirmed live — this exact symptom, this exact cause. Always start
visor for `/meta` with all three of these set:

```bash
VISOR_NATIVE=0 VISOR_PORT=8001 VISOR_ROOT_PATH=/meta python -m visor.app
```

(`VISOR_PORT` here must match `VISOR_PORT` in `.env`, which is what tells
`caddy` which port on `host.docker.internal` to reach.)

## Sharing it over Tailscale (remote attendees)

For a live workshop where attendees aren't on the same LAN, serve this over
[Tailscale](https://tailscale.com) instead of exposing it to the public
internet. Not verified from this sandbox (Tailscale isn't installed here) —
this is configuration guidance, test it once yourself before relying on it
live.

1. **Run Tailscale on the machine running Docker** (not necessarily this
   WSL distro — if you're on Docker Desktop for Windows, run Tailscale on
   the Windows host) and join your tailnet. Get the address attendees will
   use:

   ```powershell
   tailscale ip -4          # e.g. 100.x.y.z
   ```

   or use your MagicDNS name (`tailscale status`, or the Tailscale admin
   console) if you have it enabled — e.g. `mymachine.tailnet-name.ts.net`.

2. **Set `MACHINE_IP` in `.env` to that address.** This is the part that
   actually matters — it's not just about whether the port is reachable.
   `compose.yml` bakes `MACHINE_IP` into `DATAVERSE_SITEURL`
   (`http://${MACHINE_IP:-localhost}:8080`), which Dataverse embeds into
   generated links, redirects, and API response fields like
   `persistentUrl`. Leave it as `localhost` and attendees get links that
   mean nothing on their own machines.

3. **Recreate the `dataverse` container** — env vars are baked in at
   container start, not hot-reloaded:

   ```bash
   docker compose up -d --force-recreate dataverse
   ```

4. **Check your host firewall** allows inbound on 8080 for the Tailscale
   interface (on Windows, Tailscale usually adds itself as a trusted zone
   automatically, but confirm from a second device before the event —
   don't find out live).

5. **Change the default admin password before opening this up.**
   `dataverseAdmin` / `admin1` is Dataverse's own publicly-documented demo
   password — anyone on your tailnet who's read the same docs you did gets
   full superuser access (create, delete, publish anything) the moment
   they can reach the instance. Change it via the UI (account menu →
   password), or scope your Tailscale ACLs to only the specific attendees'
   devices, or both. Attendees uploading a dataset don't need admin at all
   — the API-token workflow in the smoke test above, or a plain non-admin
   account you create for them, is enough.

6. **Test from a second device on the tailnet** — not the host itself —
   before the live event: `curl http://<tailscale-address>:8080/api/info/version`
   should return the real version JSON, same as the localhost check earlier
   in this README.

### Tailscale Funnel (public internet, not just your tailnet)

Everything above shares to devices already on *your* tailnet. If attendees
don't have Tailscale installed/aren't on your tailnet at all, use
[Funnel](https://tailscale.com/kb/1223/funnel) instead to expose the Caddy
port to the public internet over HTTPS:

```bash
tailscale funnel --bg 8123   # use your actual CADDY_PORT
```

This publishes `https://<your-machine>.<tailnet>.ts.net` (port 443) →
`http://127.0.0.1:8123` on this machine — root/`/up`/`/meta` all become
reachable at that one HTTPS URL, no port number for attendees to remember
at all. Check state with `tailscale funnel status`; turn it off with
`tailscale funnel reset`.

**Prerequisite**: Funnel isn't on by default — enable it once for this node
in the Tailscale admin console (or grant the `funnel` node attribute via
your tailnet's ACL).

**This is meaningfully different from the tailnet-only sharing above: it's
the public internet, not just your tailnet.** Anyone with the URL reaches
it — there's no ACL scoping "only these attendees' devices" the way there
is with plain Tailscale. Step 5 above (change the default admin password
before opening this up) applies much harder here, since there's no
network-level restriction backing it up at all.

## Resetting

Data lives in named Docker volumes (`dv_app_data`, `dv_app_secrets`,
`dv_postgres_data`, `dv_solr_data`, `dv_solr_conf`), not a host directory.
Stop the stack and wipe them to start completely fresh — useful between
practice runs before the actual live event:

```bash
docker compose down -v
```

(`-v` is what removes the named volumes; a plain `docker compose down`
leaves them in place for next time.)

## The CDIF → Dataverse translator

Lives in the library, `metadata_enricher.exporters.dataverse`, not in this
folder — this folder stays docker/API concerns only, and is a test bench
for that exporter. Most fields map deterministically (CDIF generation
already extracted them); the one genuinely ambiguous field — Dataverse's
required, fixed Subject controlled vocabulary vs. gema's free-text
`schema:keywords` — gets one optional LLM call, config-driven
(`config/dataverse_export.yaml` at the repo root: provider/model/
temperature, same shape as every pipeline agent) and independently
enable/disable-able. `SUBJECT_CATEGORIES` and the `authorIdentifierScheme`
controlled vocabulary in that module were verified live against *this*
instance's real `/api/dataverses/:id/metadatablocks` output, not recalled
from memory. See `scripts/export_from_metadata_enricher.py` above for how
to actually run it.
