#!/bin/sh
# End-to-end update test (OPS-9): the OLD image runs on a fresh data folder, the real update
# helper moves it to the NEW image (the data must survive), then to an image that can't start
# (the helper must roll back to NEW with the data intact). Data is created through the old
# version's own API (an account, a backup job), so the test checks what people actually keep.
# Usage: scripts/upgrade_rollback_test.sh OLD_IMAGE NEW_IMAGE [BROKEN_IMAGE]
set -eu
OLD=$1
NEW=$2
BROKEN=${3:-busybox:1.37.0}
NAME=zn-upgrade-test
PORT=${ZN_TEST_PORT:-18090}
DATA=$(mktemp -d)

# The containers write the data folder as root (owner-only files), and CI runs this script
# as a normal user, so the data folder is read and cleaned through a small container.
in_data() { docker run --rm -v "$DATA":/d "$BROKEN" sh -c "$1"; }

cleanup() {
  docker rm -f "$NAME" "$NAME-rollback" zn-upgrade-helper >/dev/null 2>&1 || true
  in_data "rm -rf /d/* /d/.[!.]*" >/dev/null 2>&1 || true
  rm -rf "$DATA" 2>/dev/null || true
}
trap cleanup EXIT
fail() {
  echo "FAIL: $1"
  docker logs --tail 30 "$NAME" 2>&1 | sed 's/^/  | /' || true
  exit 1
}
wait_ok() {
  for _ in $(seq 1 90); do
    if curl -fsS "http://127.0.0.1:$PORT/api/health" 2>/dev/null | grep -q '"status":"ok"'; then return 0; fi
    sleep 2
  done
  return 1
}
image_of() { docker inspect "$NAME" --format '{{.Image}}'; }
PW="Upgrade-Admin-Pass-1"
login() {
  curl -fsS -H "Content-Type: application/json" -d "{\"username\":\"$1\",\"password\":\"$2\"}" \
    "http://127.0.0.1:$PORT/api/auth/login" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])'
}
api() {
  if [ -n "${3:-}" ]; then
    curl -fsS -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -X "$1" "http://127.0.0.1:$PORT$2" -d "$3"
  else
    curl -fsS -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -X "$1" "http://127.0.0.1:$PORT$2"
  fi
}
SEEDED=""
seed() {
  TOKEN=$(login admin "$PW") || fail "could not sign in to the old image"
  # older versions ask for a new password at the first sign-in, whatever the environment says
  body=$(printf '{"current_password":"%s","new_password":"%s"}' "$PW" "$PW-2")
  if api POST /api/security "$body" >/dev/null 2>&1; then
    PW="$PW-2"
    TOKEN=$(login admin "$PW") || fail "could not sign in after changing the password"
  fi
  if api POST /api/users '{"username":"upgrade-user","password":"Upgrade-Pass-123","role_id":"share_user"}' >/dev/null; then
    SEEDED="$SEEDED user"
  fi
  if api POST /api/backup/schedule '{"name":"Upgrade check","source_subvolume":"","destination_type":"local_snapshot","schedule":"manual"}' >/dev/null; then
    SEEDED="$SEEDED job"
  fi
  echo "   seeded:$SEEDED"
}
verify() {
  case "$SEEDED" in *user*) login upgrade-user Upgrade-Pass-123 >/dev/null || fail "the account made before the update can't sign in ($1)";; esac
  case "$SEEDED" in *job*)
    TOKEN=$(login admin "$PW") || fail "admin can't sign in ($1)"
    api GET /api/backup/schedule | grep -q "Upgrade check" || fail "the backup job made before the update is gone ($1)";;
  esac
}
result() { in_data "cat /d/update_result.json" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('result'))" 2>/dev/null; }
has_seed() { in_data "cat /d/upgrade_marker.json" 2>/dev/null | grep -q '"seed": 42'; }
helper() {
  docker run --rm --name zn-upgrade-helper \
    -v /var/run/docker.sock:/var/run/docker.sock -v "$DATA":/zettnas-data \
    "$NEW" python3 -m backend.services.self_updater --apply --target "$NAME" --image "$1" --delay 1 --data-dir /zettnas-data
}

docker pull -q "$BROKEN" >/dev/null

echo "== start the old image"
docker run -d --name "$NAME" -p "$PORT:8082" -e PORT=8082 -e ENABLE_FB=0 -e WEB_PASSWORD="$PW" \
  -e ZETTNAS_ENFORCE_PASSWORD_CHANGE=0 -v "$DATA":/app/data "$OLD" >/dev/null
wait_ok || fail "the old image never reported ok"
in_data "echo '{\"seed\": 42}' > /d/upgrade_marker.json"
seed

echo "== update to the new image"
helper "$NEW" || fail "the helper failed to update"
[ "$(image_of)" = "$(docker image inspect "$NEW" --format '{{.Id}}')" ] || fail "not running the new image after the update"
wait_ok || fail "the new image does not report ok"
has_seed || fail "data lost in the update"
verify "after the update"
[ "$(result)" = "updated" ] || fail "update_result.json says $(result), expected updated"
in_data "ls /d/backups/pre-update" | grep -q . || fail "no pre-update snapshot"

echo "== update to an image that can't start: must roll back"
good=$(image_of)
if helper "$BROKEN"; then fail "the helper reported success for a broken image"; fi
[ "$(image_of)" = "$good" ] || fail "did not roll back to the working image"
wait_ok || fail "the rolled-back container does not report ok"
has_seed || fail "data lost in the rollback"
verify "after the rollback"
[ "$(result)" = "rolled_back" ] || fail "update_result.json says $(result), expected rolled_back"
echo "PASS: update kept the data; a broken update rolled back"
