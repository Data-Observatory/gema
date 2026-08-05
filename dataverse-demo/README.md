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

## Resetting

Data lives in `./data/` (gitignored). Stop the stack (`Ctrl-C` or
`docker compose down`) and delete `./data/` to start completely fresh —
useful between practice runs before the actual live event.

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
