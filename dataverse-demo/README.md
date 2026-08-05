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

This does **not** need the DataCite → Dataverse translator (upcoming,
separate branch) — it proves the API mechanism works with a small
hand-written `dataset.json`. Once the translator exists, its output
becomes a drop-in replacement for `example_dataset.json` at the
"create dataset" step; nothing else in the script changes.

## Resetting

Data lives in `./data/` (gitignored). Stop the stack (`Ctrl-C` or
`docker compose down`) and delete `./data/` to start completely fresh —
useful between practice runs before the actual live event.

## What's next (separate branch)

The DataCite JSON → Dataverse native JSON conversion is being built
separately in `metadata_enricher` (own branch — see the main repo's
`AGENTS.md`/commit history once that lands), as a small extra agent
(config-driven like the existing 5, defaulting to a fast/cheap model,
enable/disable-able on its own) that resolves the one genuinely ambiguous
field — Dataverse's fixed Subject controlled vocabulary vs. DataCite's
free-text subjects — everything else maps deterministically. That work will
document the exact field mapping against this instance's real
`/api/dataverses/:id/metadatablocks` output once it's running, rather than
guessing Dataverse's schema from memory.
