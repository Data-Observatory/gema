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

- **http://localhost:8000/** — Dataverse UI (`dataverseAdmin` / `admin1` on a fresh stack —
  change it before sharing, see "Change the admin password" below)
- **http://localhost:8000/up/** — upload form for attendees
- **http://localhost:8000/meta/** — visor
- **http://localhost:8000/intake/** — workshop intake page (admin: `/intake/admin/`, see
  "Intake page" below; it needs its own keys in `.env` and keeps restarting until they
  are set, without affecting the rest)

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

Everything below runs from the `dataverse-demo/` folder, with the base stack already up and
bootstrapped (see "Quick start").

### 1. Prepare the Dataverse collection (once per fresh stack)

The datasets need a collection to live in, and Dataverse refuses to publish a dataset whose
collection, or any parent of it, is still unpublished. On a fresh stack **not even `root` is
published**. Create and publish a `workshop` collection with the admin API token:

```bash
TOKEN=$(./scripts/get_admin_token.sh)   # or the UI: dataverseAdmin -> API Token -> Create Token
[ -n "$TOKEN" ] || echo "no token: see the note below"
curl -sS -H "X-Dataverse-key:$TOKEN" -X POST http://localhost:8080/api/dataverses/root/actions/:publish
sed 's/"alias": "[^"]*"/"alias": "workshop"/; s/"name": "[^"]*"/"name": "GEMA! workshop"/' \
  scripts/example_collection.json > /tmp/workshop-collection.json
curl -sS -H "X-Dataverse-key:$TOKEN" -X POST http://localhost:8080/api/dataverses/root \
  --upload-file /tmp/workshop-collection.json
curl -sS -H "X-Dataverse-key:$TOKEN" -X POST http://localhost:8080/api/dataverses/workshop/actions/:publish
```

`get_admin_token.sh` only finds the token on a **fresh** stack: it reads it from the
`bootstrap` container's first-boot log, and any later `docker compose up` re-runs bootstrap,
which then only logs "bootstrapped already". If it prints nothing, reuse the token already in
`.env` (`TOKEN=$(grep ^DATAVERSE_API_TOKEN= .env | cut -d= -f2)`) or create one in the UI.
A wrong/empty token makes every call below answer `"Bad API key"` or `"User with token null
not found"`.

Each call should answer `"status":"OK"`. Publishing `root` a second time returns an error
saying it is already published, which is harmless. If you ran `scripts/smoke_test.sh`, its
`gema-demo` collection is already published and you can use that alias instead. The alias is
what goes into `DATAVERSE_COLLECTION_ALIAS` (the uploader uses the same collection).

### 2. Fill in `.env`

| Key | Required? | Default | What it is |
|---|---|---|---|
| `INTAKE_ADMIN_TOKEN` | **yes** | none | Password for `/intake/admin/`. Make a long random one: `openssl rand -hex 24`. |
| `OPENCODE_API_KEY` | **yes** | none | GEMA! always runs on the `opencode` provider (production model `deepseek-v4.1-flash` from `config/agents.yaml`). Every record makes several paid LLM calls. |
| `DATAVERSE_API_TOKEN` | for **Process** | empty | The `$TOKEN` from step 1. Without it the pages work, but **Process pending** / **Retry failed** answer "DATAVERSE_API_TOKEN is not configured". |
| `DATAVERSE_COLLECTION_ALIAS` | for **Process** | `root` | The published collection from step 1, e.g. `workshop`. |
| `INTAKE_DATAVERSE_PUBLIC_URL` | for Funnel | `DATAVERSE_SITE_URL`, else `http://${MACHINE_IP:-localhost}:8080` | Base of the *View in Dataverse* links attendees click. Through Funnel, set it to the bare Funnel URL `https://<machine>.<tailnet>.ts.net` (no path, no port: Caddy serves Dataverse at its root, so links look like `https://<machine>.<tailnet>.ts.net/dataset.xhtml?persistentId=perma:DV/...`). Set it **before** processing: each link is stored when its dataset is created. |
| `DATAVERSE_SITE_URL` | for Funnel | `http://${MACHINE_IP:-localhost}:8080` | Dataverse's own `siteUrl` (compose passes it as `DATAVERSE_SITEURL`). Dataverse writes it into the dataset page's absolute links: persistent URL / citation, metadata export and file download links. Set it to the same Funnel URL, then recreate Dataverse: `docker compose up -d dataverse` (about 2 minutes of downtime). See "Dataverse behind the Funnel URL" below. |
| `INTAKE_DEFAULT_CONTACT_EMAIL` / `INTAKE_DEFAULT_CONTACT_NAME` | no | `workshop@example.org` / `GEMA! workshop` | Dataverse requires a dataset contact. These are used when GEMA! finds no contact e-mail on the page. Use a real address you read. |
| `INTAKE_RATE_LIMIT` / `INTAKE_RATE_WINDOW` | no | `5` per `60` s | Accepted submissions per client IP per window. In a room, everyone on the venue Wi-Fi shares one public IP, so set `INTAKE_RATE_LIMIT=40` for the workshop. |
| `INTAKE_MAX_RECORDS` | no | `40` | Total records the page accepts. After that, submissions are refused. |
| `INTAKE_WORKERS` | no | `4` | Records processed in parallel. Each record runs up to 3 LLM calls at once (GEMA!'s first agent wave), so 4 workers means up to ~12 concurrent calls on your opencode key. |
| `INTAKE_RECORD_TIMEOUT` | no | `300` | Seconds before a record is given up and marked `failed`. |
| `INTAKE_SHUTDOWN_GRACE` | no | `20` | On `docker compose stop/restart`, seconds running records get to finish before they are put back to `pending`. Keep it below the service's `stop_grace_period` (35 s). |

The intake container exits at startup when `INTAKE_ADMIN_TOKEN` or `OPENCODE_API_KEY` is
empty, and keeps restarting until they are set (see Troubleshooting below). The rest of the stack
is not affected.

### 3. Start it

```bash
docker compose up -d --build intake caddy
docker logs intake          # expect "intake ready: collection=workshop workers=4 ..."
```

The image is built from the **repo root**: it installs the `gema` library from `src/` and
copies `config/`. After any change to `.env`, run the same `up -d` command again (Compose
recreates the container with the new values). After pulling code changes, keep `--build`.

| Page | Local | Through Tailscale Funnel |
|---|---|---|
| Attendee page | http://localhost:8000/intake/ | `https://<machine>.<tailnet>.ts.net/intake/` |
| Admin | http://localhost:8000/intake/admin/ | `https://<machine>.<tailnet>.ts.net/intake/admin/` |
| Direct, no Caddy (debugging only, this machine only) | http://127.0.0.1:8095/ | n/a |

Port 8000 is `CADDY_PORT`. Funnel setup is in "Tailscale Funnel" below:
`tailscale funnel --bg <CADDY_PORT>`. **Admin login**: open the admin URL and paste
`INTAKE_ADMIN_TOKEN`. The session lasts 12 h (cookie for `/intake/admin/` only). **Log out**
ends it.

### 4. Dry run (do this the day before)

1. Do steps 1–3 and check `docker logs intake` says `intake ready`.
2. From a **phone on mobile data** (not your Wi-Fi), open the Funnel `/intake/` URL and submit
   2–3 real URLs: a normal dataset landing page, one with hints, and one dead URL such as
   `https://example.org/does-not-exist`.
3. Submit one of them again. It must be refused with "already submitted by …".
4. Admin: **Close intake**, check the attendee page says "Submissions closed", then
   **Process pending**. The good URLs should turn `done` within a few minutes and the dead
   one `failed` with "URL returned HTTP 404".
5. Click *View in Dataverse* on the phone. It must open the published dataset. If it points
   at `localhost`, set `INTAKE_DATAVERSE_PUBLIC_URL` (step 2).
6. **Export results CSV**, then wipe the test data (see "Reset between runs" below), and
   delete the test datasets in Dataverse if you don't want them listed.

### 5. Workshop flow

**Before**: stack up, Funnel on, intake **open** (the default; the admin page shows "Intake is
open"), DB empty. Share the `/intake/` URL.

**During**: attendees open `/intake/` and add a *URL* (required, http/https), optional
*hints* (≤1000 characters) and a *pseudonym* (≤50). The list refreshes every 10 s. A
duplicate URL (case of the host, trailing `/` and `#fragment` ignored) is refused, naming who
submitted it first.
- The pseudonym only becomes the Dataverse keyword `group:<pseudonym>`. It never becomes an
  author or publisher.
- Hints go to GEMA! as `context_hints`, which the agents treat as **trusted** facts about the
  resource. Hints are not checked, so an attendee can steer the metadata through them.

**Admin**, at `/intake/admin/`:
1. **Delete** junk or off-topic rows. Only `pending` and `failed` rows can be deleted.
2. **Close intake** when submissions should stop. Rows submitted after you click **Process**
   are not in that batch; click it again for them.
3. **Process pending** runs every pending row in the background (`INTAKE_WORKERS` at a time).
   Each row's URL is checked for reachability, then the row goes through GEMA!, then
   `metadata_enricher.exporters.dataverse` converts it, and the dataset is created in the
   collection and published. Expect very roughly 1–3 minutes per row, so 40 rows on 4 workers take
   about 15–30 minutes. The admin list refreshes every 10 s. Clicking again while a batch runs
   only shows "A batch is already running".
4. **Retry failed** re-runs only `failed` rows. A row whose dataset was already created is
   only published, never created twice.
5. **Export results CSV** downloads every row (pseudonym, URL, hints, status, error, PID,
   link).

Statuses:

| Status | Meaning |
|---|---|
| `pending` | Submitted, waiting for **Process pending**. |
| `processing` | Running now. |
| `done` | Published. The row shows a *View in Dataverse* link. Never re-run or re-uploaded. |
| `failed` | Stopped with a short reason. The reason is shown on the admin page and in the CSV, not on the public page. One automatic retry already covered network errors, HTTP 5xx and rate limits. |

**After**: export the CSV, then reset (below) before the next workshop.

### Logs

`intake.log` sits on the `intake_data` volume (`/data/intake.log` inside the container,
rotated at 2 MB, 3 backups). It holds every submission, admin action, record start, failure
reason and batch summary, plus GEMA!'s own log lines.

```bash
docker exec intake tail -f /data/intake.log        # or: docker logs -f intake (same lines)
docker exec intake grep -E "failed|batch" /data/intake.log
```

### Reset between runs

The records live in `/data/intake.db` on the `intake_data` volume. This wipes the list and
the log and leaves Dataverse alone:

```bash
docker compose rm -sf intake
docker volume rm dataverse-demo_intake_data
docker compose up -d intake
```

The volume name is `<compose project>_intake_data`. The project defaults to the folder name;
check with `docker volume ls | grep intake`. `docker compose down -v` also wipes it, but
wipes Dataverse along with it. Datasets already published in Dataverse stay there. Delete
them from the Dataverse UI if needed.

### Troubleshooting

- **Dataverse is unreachable after a reboot** (`docker ps` shows `dataverse` restarting,
  `docker logs dataverse` loops on `lookup postgres ... server misbehaving`): `postgres` and
  `smtp` stayed stopped, because their `restart: on-failure` policy does not bring them back
  after a clean shutdown. Run `docker compose up -d postgres smtp` (or `docker compose up -d`)
  and wait a couple of minutes for `curl http://localhost:8080/api/info/version`.
- **`intake` keeps restarting** (`docker ps` shows `Restarting`): run `docker logs intake`.
  `intake: configuration error: INTAKE_ADMIN_TOKEN is not set` (or `OPENCODE_API_KEY`) means
  you should set the key in `.env` and run `docker compose up -d intake`.
- **Process says "DATAVERSE_API_TOKEN is not configured"**: set it (step 2) and run
  `docker compose up -d intake`.
- **Every record fails at "publish dataset: Dataverse HTTP …"** with a message about an
  unpublished collection or dataverse: the collection, or `root`, is not published. Do
  step 1, then **Retry failed** (the drafts already created are only published).
- **"create dataset: Dataverse HTTP 404"** means the alias in `DATAVERSE_COLLECTION_ALIAS`
  does not exist. **HTTP 401** means the token is wrong or expired.
- **Attendees see "Too many submissions from your address"**: they share an IP (venue NAT,
  or Funnel not passing the client IP through; see Security notes). Raise `INTAKE_RATE_LIMIT` and run
  `docker compose up -d intake`.
- **"URL returned HTTP 403"**, or other 4xx, means the site refuses automated requests or the
  page is gone. Ask the attendee for another URL, delete the row, and let them resubmit.
- **Many `timed out after 300s` or provider 429 errors**: too many concurrent LLM calls.
  Lower `INTAKE_WORKERS` (e.g. `2`), recreate the container, and **Retry failed**. Successful
  LLM answers are cached, so retries are faster. A timed-out record keeps running in the
  background until GEMA! returns, but it writes nothing more.
- **Deleting a `failed` row whose admin entry shows a PID** leaves that dataset as an
  unpublished *draft* in Dataverse. Delete the draft in the Dataverse UI (log in as admin,
  open the collection, filter on drafts), or use **Retry failed** instead.
- **Stopped or restarted the container mid-batch** (`docker compose stop/restart intake`,
  `up -d` recreating it, a reboot): on SIGTERM the batch stops claiming rows, rows already
  running get `INTAKE_SHUTDOWN_GRACE` seconds (default 20) to finish, and anything still
  running after that goes back to `pending`, marked "Interrupted by a shutdown". Rows that
  had not started yet are left `pending`, untouched. Compose waits 35 s
  (`stop_grace_period`) before killing the container. After a hard kill (`docker kill`, power
  loss), rows left `processing` are put back to `pending` at the next start, marked
  "Interrupted by a restart". Either way, click **Process pending** again. A row whose
  dataset already exists is only published, never created twice.

### Running outside Docker / tests

From the repo root (Dataverse reached on the host port):

```bash
INTAKE_ADMIN_TOKEN=... OPENCODE_API_KEY=... DATAVERSE_API_TOKEN=... \
DATAVERSE_URL=http://localhost:8080 DATAVERSE_COLLECTION_ALIAS=workshop \
INTAKE_DATA_DIR=./intake-data INTAKE_GEMA_CONFIG=config/agents.yaml \
INTAKE_EXPORT_CONFIG=config/dataverse_export.yaml PYTHONPATH=dataverse-demo/intake \
uv run --with fastapi --with python-multipart --with jinja2 --with uvicorn \
  uvicorn --factory intake_app.main:build_app --port 8095
```

Tests (no network, no LLM, no Dataverse):

```bash
uv run --with fastapi --with python-multipart --with jinja2 pytest dataverse-demo/intake/tests
```

### Security notes

The server fetches attendee-submitted URLs, so non-public addresses (IP literals,
`localhost`, single-label and `.local`-style names) are refused at submit time, and DNS and
every redirect hop are checked again before the fetch. Treat `INTAKE_ADMIN_TOKEN` like the
Dataverse token: anyone holding it can publish to the instance.

**Which client IP the rate limit sees** (checked live on the local stack, 2026-11-25):
Caddy overwrites `X-Real-IP` with its `{client_ip}`, and trusts `X-Forwarded-For` only
from the docker network gateway `10.213.77.1` (`trusted_proxies` in `Caddyfile`).
- **LAN / venue Wi-Fi clients hitting `http://<lan-ip>:<CADDY_PORT>` directly** keep their
  own source address, so their IP is what counts and a forged `X-Forwarded-For` is ignored.
  (Before this was narrowed from "all private ranges", a LAN client could forge any IP and
  dodge the limit.) Tailnet clients on `100.x` addresses behave the same way.
- **Everything connecting from this host's loopback** (`127.0.0.1:<CADDY_PORT>`) reaches
  Caddy from the gateway address, so `X-Forwarded-For` is trusted: the rightmost entry that
  is not the gateway wins. **Tailscale Funnel goes this way**: `tailscaled` terminates TLS
  and proxies to `http://127.0.0.1:<CADDY_PORT>`, and its proxy is expected to set
  `X-Forwarded-For` to the address it received the request from. Whether that is the
  visitor's real public IP for Funnel traffic was **not verified live** (Funnel
  was off when this was checked). Check it on the dry run: submit from a phone on mobile
  data and look at `docker exec intake grep "submitted by" /data/intake.log`. If every
  Funnel visitor shows the same address (e.g. `10.213.77.1` or a `100.x` relay address), the
  limit is effectively global; raise `INTAKE_RATE_LIMIT` accordingly.
- Local processes on this host can set any `X-Forwarded-For`; that is accepted.
- If you change the subnet in `compose.yml`, change `trusted_proxies` to its `.1` gateway.

## Caddy (single entrypoint for Tailscale)

If you're sharing this over Tailscale (below) and don't want to open/remember
three separate ports, `caddy` (service in `compose.yml`, `Caddyfile` at the
repo root of this folder) fans out one port to path-based routes:

- **`/intake`** → the workshop intake page (see above). Caddy sets `X-Real-IP` from its
  own `{client_ip}` (global `trusted_proxies` = the docker gateway only), which the intake's
  per-IP rate limit uses. See "Which client IP the rate limit sees" under Security notes.
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

2. **Set `MACHINE_IP` in `.env` to that address** (through Funnel, set `DATAVERSE_SITE_URL`
   to the Funnel URL instead; it takes precedence). This is the part that
   actually matters — it's not just about whether the port is reachable.
   `compose.yml` bakes `MACHINE_IP` into `DATAVERSE_SITEURL`
   (`${DATAVERSE_SITE_URL:-http://${MACHINE_IP:-localhost}:8080}`), which Dataverse embeds into
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
   they can reach the instance. Dataverse has no API for this; change it in
   the UI (log in, account menu → Account Information → Change Password), or
   use *Forgot password?* on the login page: the reset e-mail lands in the
   stack's mail catcher at http://localhost:1080 (the admin's address is
   `dataverse@mailinator.com`). Keep the new one in `.env` as
   `DATAVERSE_ADMIN_PASSWORD` (no container reads it; nothing in the stack
   uses the password after bootstrap, everything uses API tokens). Also
   scope your Tailscale ACLs to only the specific attendees' devices. Attendees uploading a dataset don't need admin at all
   — the API-token workflow in the smoke test above, or a plain non-admin
   account you create for them, is enough.

6. **Test from a second device on the tailnet** — not the host itself —
   before the live event: `curl http://<tailscale-address>:8080/api/info/version`
   should return the real version JSON, same as the localhost check earlier
   in this README.

**Other default credentials and open ports** (not changed by the steps above): the
Postgres password is `secret` (hardcoded in `compose.yml`, and Postgres is published on
`0.0.0.0:5432`), and Payara admin (4848), JDWP debug (9009), JMX (8686), Solr (8983) and
the mail catcher (25/1080) are published on all interfaces too. Funnel only exposes the Caddy
port, but anyone on the same LAN (e.g. the venue Wi-Fi) can reach these directly: firewall
them, or prefix those `ports:` entries with `127.0.0.1:` and recreate the containers.

### Tailscale Funnel (public internet, not just your tailnet)

Everything above shares to devices already on *your* tailnet. If attendees
don't have Tailscale installed/aren't on your tailnet at all, use
[Funnel](https://tailscale.com/kb/1223/funnel) instead to expose the Caddy
port to the public internet over HTTPS:

```bash
tailscale funnel --bg 8123   # use your actual CADDY_PORT
```

This publishes `https://<your-machine>.<tailnet>.ts.net` (port 443) →
`http://127.0.0.1:8123` on this machine — root/`/up`/`/meta`/`/intake` all become
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

### Dataverse behind the Funnel URL

Checked on the local stack (Funnel itself was off, so this was done by calling Caddy with the
Funnel `Host` header):
- Caddy serves Dataverse at the root of the Funnel URL. Dataset pages, collection pages and
  the login page render: their links are root-relative and work under any host name.
- What does **not** follow the request host is everything Dataverse builds from
  `siteUrl`: the persistent URL / citation link, the metadata export links, file download
  links and the schema.org / Croissant JSON-LD embedded in the page. With the default
  (`http://localhost:8080`) those point at `localhost` for an attendee on the internet. Set
  `DATAVERSE_SITE_URL=https://<machine>.<tailnet>.ts.net` in `.env` and recreate Dataverse
  (`docker compose up -d dataverse`).
- Local use keeps working after that change: `http://localhost:8080` and
  `http://localhost:<CADDY_PORT>` still serve every page. Only those absolute links point at
  the Funnel host, so they only open while Funnel is on.
- Metadata exports cached before the change (the JSON-LD, the BibTeX in the page) keep the
  old `localhost` URL until the dataset is published again. Datasets created after the
  change are fine.
- Payara does not honour `X-Forwarded-Proto`, so the few absolute links Payara builds from
  the request itself (not from `siteUrl`) say `http://<funnel-host>/...`, and Funnel only
  answers on HTTPS. Attendees viewing a dataset do not hit these. Log in as admin locally,
  not through the Funnel URL.

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
