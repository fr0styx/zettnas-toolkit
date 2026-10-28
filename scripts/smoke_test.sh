#!/bin/sh
# Starts an image and checks that it serves the app (OPS-08, OPS-10).
# Usage: scripts/smoke_test.sh IMAGE [PLATFORM] [PORT] [WAIT_SECONDS]
#   IMAGE     a tag or digest; for a multi-arch image the platform's own manifest is run,
#             because Docker refuses to run a second platform of a digest it already
#             pulled ("cannot overwrite digest")
#   PLATFORM  linux/amd64 (default) or linux/arm64 (needs QEMU on an amd64 host)
# Failures print a GitHub annotation with the last 40 lines of the container log.
# Optional budgets (PERF-28, PERF-29): STARTUP_BUDGET_SECS, the most seconds from start to the
# first healthy /api/health; IMAGE_BUDGET_MB, the most MB the platform's layers may download.
set -eu
IMAGE=$1
PLATFORM=${2:-linux/amd64}
PORT=${3:-18082}
WAIT=${4:-120}
ARCH=${PLATFORM#*/}
NAME="zettnas-smoke-$ARCH"

fail() {
  logs=$(docker logs "$NAME" 2>&1 | tail -40 | sed 's/%/%25/g' | awk 'BEGIN{ORS="%0A"} {print}')
  echo "::error title=Smoke test ($PLATFORM)::$1%0A--- container log (last 40 lines) ---%0A$logs"
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  exit 1
}

repo=${IMAGE%%@*}
case "${repo##*/}" in *:*) repo=${repo%:*} ;; esac
ref=$IMAGE
platform_digest=$(docker buildx imagetools inspect --raw "$IMAGE" 2>/dev/null | python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
for m in doc.get("manifests") or []:
    p = m.get("platform") or {}
    if p.get("os") == "linux" and p.get("architecture") == sys.argv[1]:
        print(m["digest"])
        break
' "$ARCH" || true)
[ -n "$platform_digest" ] && ref="$repo@$platform_digest"
echo "Smoke test: $ref ($PLATFORM)"

if [ -n "${IMAGE_BUDGET_MB:-}" ]; then
  mb=$(docker buildx imagetools inspect --raw "$ref" | python3 -c '
import json, sys
doc = json.load(sys.stdin)
print(round(sum(layer["size"] for layer in doc.get("layers") or []) / 1e6))
')
  echo "image: $mb MB to download (budget $IMAGE_BUDGET_MB MB)"
  [ "$mb" -gt 0 ] && [ "$mb" -le "$IMAGE_BUDGET_MB" ] || fail "the image is $mb MB to download, over its $IMAGE_BUDGET_MB MB budget"
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --platform "$PLATFORM" --name "$NAME" -p "$PORT:8082" -e PORT=8082 -e ENABLE_FB=0 "$ref" >/dev/null ||
  fail "the container did not start"
started=$(date +%s)

case "$ARCH" in amd64) want=x86_64 ;; arm64) want=aarch64 ;; *) want=$ARCH ;; esac
got=$(docker exec "$NAME" uname -m 2>/dev/null || echo unknown)
[ "$got" = "$want" ] || fail "the container runs $got, expected $want"

ok=0
tries=$WAIT
for _ in $(seq 1 "$tries"); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
[ "$ok" = 1 ] || fail "no healthy /api/health within $WAIT seconds"
took=$(($(date +%s) - started))
echo "first healthy answer after ${took}s"
if [ -n "${STARTUP_BUDGET_SECS:-}" ] && [ "$took" -gt "$STARTUP_BUDGET_SECS" ]; then
  fail "the first healthy answer came after ${took}s, over the ${STARTUP_BUDGET_SECS}s budget"
fi
curl -fsS -o /tmp/zettnas-smoke-index.html "http://127.0.0.1:$PORT/" || fail "GET / failed"
grep -qi "<html" /tmp/zettnas-smoke-index.html || fail "index.html not served"
code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/users")
[ "$code" = 401 ] || fail "/api/users without a session returned $code, expected 401"
bad=$(docker logs "$NAME" 2>&1 | grep -E "Traceback|CRITICAL" | head -5 || true)
[ -z "$bad" ] || fail "errors in the startup log: $(echo "$bad" | sed 's/%/%25/g' | awk 'BEGIN{ORS="%0A"} {print}')"
docker rm -f "$NAME" >/dev/null
echo "PASS: $ref started on $PLATFORM and served the app"
[ -z "${GITHUB_STEP_SUMMARY:-}" ] || echo "$PLATFORM: $ref started and served the app" >> "$GITHUB_STEP_SUMMARY"
