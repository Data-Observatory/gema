# Dataverse demo stack

A local, disposable Dataverse instance for the live exercise: attendees fill
in a resource description, run it through `metadata-enricher`/visor to get
DataCite JSON, convert that to Dataverse's native JSON (separate, upcoming
work — see below), and upload the resulting dataset to *this* instance so
everyone can see how it renders.

This is `compose.yml` from IQSS's own official demo/evaluation setup,
essentially unmodified — see the top of that file for the exact two
deviations (the "demo" persona pre-selected instead of "dev", and the
blocked-API key made configurable via `.env` instead of hardcoded). Source:
[IQSS/dataverse — Demo or Evaluation](https://guides.dataverse.org/en/6.2/container/running/demo.html).

## Quick start

```bash
cd dataverse-demo
cp .env.example .env
# edit .env: at minimum change BLOCKED_API_KEY to something only you know
docker compose up
```

First boot takes a few minutes (Postgres + Solr + the Dataverse app itself
starting, then the `bootstrap` container runs `demo/init.sh` to configure a
fresh instance). Watch for `bootstrap` exiting with "Done, your instance has
been configured for demo or eval." — that's the signal everything else is up.

Visit **http://localhost:8080** and log in:

- username: `dataverseAdmin`
- password: `admin1`

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

This never needed the DataCite → Dataverse translator to prove the API
mechanism works — that's `example_dataset.json`'s whole point, a small
hand-written payload. The translator now exists
(`metadata_enricher.exporters.dataverse`, separate branch) — use
`scripts/export_from_metadata_enricher.py` to generate a real one from an
actual metadata-enricher output instead:

```bash
cd /path/to/repo/root   # needs metadata_enricher importable
uv run python dataverse-demo/scripts/export_from_metadata_enricher.py \
  tests/fixtures/golden/expected/sample_input01.json \
  --output dataverse-demo/scripts/example_dataset.json
```

Verified live: this exact command's output was POSTed to a real running
instance and accepted (`{"status":"OK",...}`), producing a real dataset
with the correct title/author pulled straight from actual DataCite
output — not a synthetic example. Without `--classify`, Subject defaults
to `"Other"` (no LLM call, no cost); add `--classify` to run the real
classification call (needs the provider's API key set, same as running
metadata-enricher itself). Either way it prints any warnings — e.g. no
contact email found anywhere in the source metadata, a real gap between
DataCite and Dataverse's required fields, not a bug — so check those
before publishing.

## Upload proxy (for attendees without API tooling)

`uploader/` is a very light FastAPI service — one form, no auth of its own,
no database — that takes a Dataverse-native JSON payload (paste or file
upload) and forwards it to this instance's native API
(`POST /api/dataverses/:alias/datasets`), the same call `scripts/smoke_test.sh`
makes by hand. It's for attendees who have metadata-enricher/visor output
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

## Caddy (single entrypoint for Tailscale)

If you're sharing this over Tailscale (below) and don't want to open/remember
three separate ports, `caddy` (service in `compose.yml`, `Caddyfile` at the
repo root of this folder) fans out one port to path-based routes:

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

## The DataCite → Dataverse translator

Lives in `metadata_enricher.exporters.dataverse` (separate branch —
`dataverse-export-agent`), not in this folder — this stays docker/API
concerns only. Most fields map deterministically (DataCite already
extracted them correctly); the one genuinely ambiguous field — Dataverse's
required, fixed Subject controlled vocabulary vs. DataCite's free-text
subjects — gets one optional LLM call, config-driven
(`config/dataverse_export.yaml` at the repo root: provider/model/
temperature, same shape as every pipeline agent) and independently
enable/disable-able. `SUBJECT_CATEGORIES` and the `authorIdentifierScheme`
controlled vocabulary in that module were verified live against *this*
instance's real `/api/dataverses/:id/metadatablocks` output, not recalled
from memory. See `scripts/export_from_metadata_enricher.py` above for how
to actually run it.
