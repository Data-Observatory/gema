#!/bin/bash
# Prints the dataverseAdmin API token created by the bootstrap container on
# first boot. Extracted from bootstrap's own logs (it prints the full user
# object, including apiToken, when setup-all.sh creates the admin user) —
# there is no "log in via curl and get a token" endpoint in Dataverse; the
# officially documented way is the UI's Account -> API Token page. This
# recovers the same token bootstrap already generated, so you don't have to
# open a browser just to script the smoke test.
#
# Only works once, right after `docker compose up` on a fresh ./data/ — the
# token stays valid (see its expiry in the output) but this script can only
# find it in bootstrap's logs, which only exist while that container hasn't
# been removed. If you need a token later and this comes up empty, get one
# from the UI instead: log in as dataverseAdmin, click your name -> API
# Token -> Create Token.

set -euo pipefail

TOKEN=$(docker logs bootstrap 2>&1 | grep -o '[0-9a-f]\{8\}-[0-9a-f]\{4\}-[0-9a-f]\{4\}-[0-9a-f]\{4\}-[0-9a-f]\{12\}' | head -1)

if [ -z "$TOKEN" ]; then
  echo "Could not find a token in bootstrap's logs — get one from the UI instead" >&2
  echo "(log in as dataverseAdmin, click your name -> API Token -> Create Token)." >&2
  exit 1
fi

echo "$TOKEN"
