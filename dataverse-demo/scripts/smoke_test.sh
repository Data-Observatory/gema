#!/bin/bash
# API-only smoke test for the dataverse-demo stack, mirroring the manual
# checklist in IQSS's own demo guide (log in, publish root, create a
# collection, create a dataset, upload a file, publish the dataset) —
# https://guides.dataverse.org/en/6.2/container/running/demo.html
#
# Every command here is real, verified against the current develop-branch
# API guide (native-api.rst) and run once against a live instance before
# being committed — not copied from memory.
#
# This does NOT need the DataCite -> Dataverse translator (separate,
# upcoming work). It proves the API mechanism works — auth, create,
# upload, publish — using a small hand-written dataset.json. Once the
# translator exists, its output is a drop-in replacement for
# example_dataset.json at the "create dataset" step; everything else in
# this script is unaffected.
#
# Usage:
#   ./get_admin_token.sh                    # find your token first
#   API_TOKEN=<token> ./smoke_test.sh
#
# Safe to re-run against a fresh ./data/ (see ../README.md's "Resetting"
# section) — COLLECTION_ALIAS must be unique per instance-lifetime, so
# re-running against the SAME already-populated instance will fail at the
# "create collection" step with a "such a collection already exists"
# error; that's expected, not a bug in this script.

set -euo pipefail

SERVER_URL="${SERVER_URL:-http://localhost:8080}"
COLLECTION_ALIAS="${COLLECTION_ALIAS:-gema-demo}"

if [ -z "${API_TOKEN:-}" ]; then
  echo "Set API_TOKEN first — run ./get_admin_token.sh to find it." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 1. Publish root collection ==="
curl -sS -H "X-Dataverse-key:$API_TOKEN" -X POST "$SERVER_URL/api/dataverses/root/actions/:publish"
echo ""

echo "=== 2. Create collection ($COLLECTION_ALIAS) ==="
# example_collection.json's "alias" field is fixed — override it inline if
# you need a different alias without editing the committed file.
sed "s/\"alias\": \"[^\"]*\"/\"alias\": \"$COLLECTION_ALIAS\"/" "$SCRIPT_DIR/example_collection.json" > /tmp/dv-demo-collection.json
curl -sS -H "X-Dataverse-key:$API_TOKEN" -X POST "$SERVER_URL/api/dataverses/root" --upload-file /tmp/dv-demo-collection.json
echo ""

echo "=== 3. Create dataset ==="
CREATE_RESPONSE=$(curl -sS -H "X-Dataverse-key:$API_TOKEN" -X POST "$SERVER_URL/api/dataverses/$COLLECTION_ALIAS/datasets" \
  --upload-file "$SCRIPT_DIR/example_dataset.json" -H 'Content-type:application/json')
echo "$CREATE_RESPONSE"
PERSISTENT_ID=$(echo "$CREATE_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['persistentId'])")
echo "persistentId=$PERSISTENT_ID"
echo ""

echo "=== 4. Upload a file ==="
echo '{"note": "placeholder file — replace with a real dataset file"}' > /tmp/dv-demo-sample.json
curl -sS -H "X-Dataverse-key:$API_TOKEN" -X POST \
  -F "file=@/tmp/dv-demo-sample.json" \
  -F 'jsonData={"description":"Smoke test file.","categories":["Data"], "restrict":"false"}' \
  "$SERVER_URL/api/datasets/:persistentId/add?persistentId=$PERSISTENT_ID"
echo ""

echo "=== 5. Publish collection ==="
curl -sS -H "X-Dataverse-key:$API_TOKEN" -X POST "$SERVER_URL/api/dataverses/$COLLECTION_ALIAS/actions/:publish"
echo ""

echo "=== 6. Publish dataset ==="
curl -sS -H "X-Dataverse-key: $API_TOKEN" -X POST \
  "$SERVER_URL/api/datasets/:persistentId/actions/:publish?persistentId=$PERSISTENT_ID&type=major"
echo ""

echo "=== Done — view it at: $SERVER_URL/citation?persistentId=$PERSISTENT_ID ==="
