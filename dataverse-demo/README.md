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

Do the same smoke test the official guide recommends before relying on this
for a live audience: log in, publish the root collection, create a
collection, create a dataset, upload a file, publish the dataset.

## Requirements

- Docker (the official guide calls Windows support "experimental" — Mac/Linux
  are the tested platforms)
- ~8GB RAM free, since this boots Postgres + Solr + Payara + a mail catcher
  + two previewer-registration containers all at once

**Not yet verified from this environment**: this repo's dev sandbox (WSL,
no Docker Desktop integration enabled for this distro) can write and review
these files but cannot actually run `docker compose up` here. Treat the
first real boot — by whoever has Docker available — as the actual proof
this works, not a formality.

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
