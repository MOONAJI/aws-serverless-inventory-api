#!/usr/bin/env bash
# Exercises the four CRUD endpoints (plus list) against the deployed API.
# Usage: API_URL=https://<api-id>.execute-api.us-east-1.amazonaws.com ./scripts/smoke-test.sh | tee evidence/smoke-test.txt
set -euo pipefail
: "${API_URL:?Set API_URL, e.g. https://abc123.execute-api.us-east-1.amazonaws.com}"
API_URL="${API_URL%/}"

show() { printf '\n### %s\n' "$1"; }
status() { curl -sS -o /dev/null -w 'HTTP %{http_code}\n' "${@}"; }

show "POST /items (create)"
resp=$(curl -sS -w '\nHTTP %{http_code}' -X POST "$API_URL/items" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Oscilloscope","category":"Lab equipment","quantity":3,"location":"Lab 2","min_stock":1}')
echo "$resp"
ITEM_ID=$(printf '%s' "$resp" | head -n1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["item_id"])')

show "GET /items/$ITEM_ID (read)"
curl -sS -w '\nHTTP %{http_code}\n' "$API_URL/items/$ITEM_ID"

show "PUT /items/$ITEM_ID (update quantity to 2)"
curl -sS -w '\nHTTP %{http_code}\n' -X PUT "$API_URL/items/$ITEM_ID" \
  -H 'Content-Type: application/json' -d '{"quantity":2}'

show "GET /items (list, bonus)"
curl -sS -w '\nHTTP %{http_code}\n' "$API_URL/items"

show "DELETE /items/$ITEM_ID (delete)"
curl -sS -w '\nHTTP %{http_code}\n' -X DELETE "$API_URL/items/$ITEM_ID"

show "GET /items/$ITEM_ID after delete (expect 404)"
status "$API_URL/items/$ITEM_ID"

show "POST /items without name (expect 400)"
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$API_URL/items" \
  -H 'Content-Type: application/json' -d '{"quantity":1}'
