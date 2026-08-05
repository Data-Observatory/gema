#!/bin/bash

# Verbatim from IQSS's official demo bootstrap script:
# https://github.com/IQSS/dataverse/blob/develop/modules/container-configbaker/scripts/bootstrap/demo/init.sh
# BLOCKED_API_KEY is read from the environment (set via ../compose.yml's
# bootstrap service, sourced from a .env file next to compose.yml — see
# ../README.md) rather than the hardcoded "unblockme" default ever
# actually being relied on for anything beyond a first local test.

set -euo pipefail

# Set some defaults
DATAVERSE_URL=${DATAVERSE_URL:-"http://dataverse:8080"}
export DATAVERSE_URL

BLOCKED_API_KEY=${BLOCKED_API_KEY:-"unblockme"}
export BLOCKED_API_KEY

# --insecure is used so we can configure a few things but
# later in this script we'll apply the changes as if we had
# run the script without --insecure.
echo "Running base setup-all.sh..."
"${BOOTSTRAP_DIR}"/base/setup-all.sh --insecure -p=admin1 | tee /tmp/setup-all.sh.out

echo ""
echo "Setting DOI provider to \"FAKE\"..."
curl -sS -X PUT -d FAKE "${DATAVERSE_URL}/api/admin/settings/:DoiProvider"

API_TOKEN=$(grep apiToken "/tmp/setup-all.sh.out" | jq ".data.apiToken" | tr -d \")
export API_TOKEN

ROOT_COLLECTION_JSON=/scripts/bootstrap/demo/config/dataverse-complete.json
if [ -f $ROOT_COLLECTION_JSON ]; then
  echo ""
  echo "Updating root collection based on $ROOT_COLLECTION_JSON..."
  curl -sS -X PUT -H "X-Dataverse-key:$API_TOKEN" "$DATAVERSE_URL/api/dataverses/:root" --upload-file $ROOT_COLLECTION_JSON
fi

echo ""
echo "Revoke the key that allows for creation of builtin users..."
curl -sS -X DELETE "${DATAVERSE_URL}/api/admin/settings/:BuiltinUsersKey"

# TODO: stop using these deprecated database settings. See https://github.com/IQSS/dataverse/pull/11454
echo ""
echo "Set key for accessing blocked API endpoints..."
curl -sS -X PUT -d "$BLOCKED_API_KEY" "${DATAVERSE_URL}/api/admin/settings/:BlockedApiKey"

echo ""
echo "Set policy to only allow access to admin APIs with with a key..."
curl -sS -X PUT -d unblock-key "${DATAVERSE_URL}/api/admin/settings/:BlockedApiPolicy"

echo ""
echo "Block admin and other sensitive API endpoints..."
curl -sS -X PUT -d 'admin,builtin-users' "${DATAVERSE_URL}/api/admin/settings/:BlockedApiEndpoints"

echo ""
echo "Done, your instance has been configured for demo or eval. Have a nice day!"
