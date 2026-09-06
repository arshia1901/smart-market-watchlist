#!/usr/bin/env bash
#
# Smart Market Watchlist - one command for the whole stack.
#
#   ./run.sh start [--fresh]      bring everything up and wait until it serves
#   ./run.sh stop                 stop the containers, keep the data
#   ./run.sh status               what is running, and is it healthy
#   ./run.sh logs [service...]    follow logs
#   ./run.sh demo                 the failure demonstrations, listed
#   ./run.sh test                 run both test suites in containers
#   ./run.sh reset                stop and destroy volumes (re-seeds on next start)
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

WEB_PORT="${WEB_PORT:-8080}"
API_PORT="${API_PORT:-8000}"
READY_TIMEOUT="${READY_TIMEOUT:-420}"

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
  BOLD=''; DIM=''; RED=''; GREEN=''; YELLOW=''; RESET=''
fi

info() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
warn() { printf '%s==>%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

COMPOSE=()

preflight() {
  command -v docker >/dev/null 2>&1 || die \
$'Docker is not installed.\n       Install Docker Desktop: https://docs.docker.com/desktop/'

  docker info >/dev/null 2>&1 || die \
$'the Docker daemon is not running.\n       Start Docker Desktop, wait for the whale to stop animating, then retry.'

  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    die 'Docker Compose v2 not found. Update Docker Desktop.'
  fi
}

port_busy() {
  command -v lsof >/dev/null 2>&1 || return 1
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

check_ports() {
  for p in "$WEB_PORT" "$API_PORT"; do
    port_busy "$p" && die "port $p is already in use.
       Free it, or choose another:  WEB_PORT=9080 API_PORT=9000 ./run.sh start"
  done
  return 0
}

wait_ready() {
  local deadline=$((SECONDS + READY_TIMEOUT)) spin='|/-\' i=0
  printf '%s==>%s waiting for the stack' "$BOLD" "$RESET"
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 2 "http://localhost:${WEB_PORT}/healthz" >/dev/null 2>&1 &&
       curl -fsS --max-time 2 "http://localhost:${API_PORT}/healthz" >/dev/null 2>&1; then
      printf '\r%s==>%s stack is up%*s\n' "$BOLD" "$RESET" 24 ''
      return 0
    fi
    i=$(( (i + 1) % 4 ))
    printf '\r%s==>%s waiting for the stack %s ' "$BOLD" "$RESET" "${spin:$i:1}"
    sleep 1
  done
  printf '\n'
  warn "not ready after ${READY_TIMEOUT}s. Last 40 log lines:"
  "${COMPOSE[@]}" logs --tail=40 || true
  die 'startup failed. Try: ./run.sh reset && ./run.sh start'
}

cmd_start() {
  local fresh=0
  for a in "$@"; do [[ "$a" == "--fresh" ]] && fresh=1; done

  check_ports
  if (( fresh )); then
    info 'destroying existing volumes'
    "${COMPOSE[@]}" down --volumes --remove-orphans
  fi

  info 'building images and starting services'
  info "${DIM}first run pulls base images and builds the frontend - a few minutes${RESET}"
  local started=$SECONDS
  "${COMPOSE[@]}" up --detach --build --remove-orphans
  wait_ready

  printf '\n  %sWatchlist%s   %shttp://localhost:%s%s\n' "$BOLD" "$RESET" "$GREEN" "$WEB_PORT" "$RESET"
  printf '  %sTwo users%s   http://localhost:%s/?user=asha   and   /?user=ravi\n' "$DIM" "$RESET" "$WEB_PORT"
  printf '  %sAPI docs%s    http://localhost:%s/docs\n' "$DIM" "$RESET" "$API_PORT"
  printf '  %sDemos%s       ./run.sh demo\n' "$DIM" "$RESET"
  printf '  %sReady in%s    %ss\n\n' "$DIM" "$RESET" "$((SECONDS - started))"
}

cmd_stop() { info 'stopping (data is preserved)'; "${COMPOSE[@]}" stop; }

cmd_status() {
  "${COMPOSE[@]}" ps
  printf '\n'
  for pair in "api:${API_PORT}" "web:${WEB_PORT}"; do
    local name="${pair%%:*}" port="${pair##*:}"
    if curl -fsS --max-time 2 "http://localhost:${port}/healthz" >/dev/null 2>&1; then
      printf '  %-4s %sserving%s   http://localhost:%s\n' "$name" "$GREEN" "$RESET" "$port"
    else
      printf '  %-4s %snot responding%s on http://localhost:%s\n' "$name" "$RED" "$RESET" "$port"
    fi
  done
  printf '\n'
}

cmd_logs() { if (( $# )); then "${COMPOSE[@]}" logs --tail=100 -f "$@";
             else "${COMPOSE[@]}" logs --tail=100 -f; fi; }

cmd_test() {
  info 'backend'
  # Bind-mount the tests from the host. The image bakes tests/ in at build time, so
  # without this an edited test silently runs its OLD version from the image - which
  # is how a fixture change went unnoticed for four runs during development.
  "${COMPOSE[@]}" run --rm --no-deps -T \
    -v "$PWD/services/tests:/srv/tests:ro" api python -m pytest -q
  info 'frontend'
  # The anonymous volume over /w/node_modules is load-bearing. Without it, npm ci
  # inside this Linux container writes linux-x64 binaries straight into the host's
  # node_modules through the bind mount, and the next `ng build` on the Mac fails
  # with "esbuild installed for another platform". That happened.
  docker run --rm -v "$PWD/web":/w -v /w/node_modules -w /w node:22-bookworm-slim \
    sh -c 'npm ci --silent --no-audit --no-fund && npm test'
}

cmd_demo() {
  cat <<'DEMO'
The design claims no component outside the read path can take the product down.
Each of these is that claim, checkable in one command. Keep the page open throughout.

  0  Start empty. Sign in, add two or three stocks from the search box, and watch the
     batch strip go 0 -> 3 tracked. Within a minute each has a real BSE price and a
     provisional sigma measured from that stock's own intraday bars.

  0b The canary - drive the whole pipeline by hand, market open or not. Search "arshia",
     add it, then:
       curl -X POST 'localhost:8000/api/test/warmup?symbol=ARSHIA&price=100&sigma=0.0007'
       curl -X POST 'localhost:8000/api/test/quote?symbol=ARSHIA&price=100.15'   # ~2 sigma
     On the next tick the row moves: +0.15%, band per N. Its chip reads TEST; it never
     touches an exchange, and the endpoints refuse any real symbol.

  1  docker compose stop ingestion    prices stop updating and visibly AGE: the
                                      freshness chip walks live -> delayed -> stale
                                      while the list keeps serving. The strip shows
                                      ingestion going red as it misses its cadence.
     docker compose start ingestion   it resumes; nothing was lost.

  2  docker compose stop cache        the cache is an accelerator, not a source of
                                      truth. The API falls back to Postgres and
                                      "served by" in the header flips to `store`.
     docker compose start cache

  3  docker compose stop statistics   sigma freezes. On restart the engine rebuilds
                                      every window from the time series rather than
                                      resuming with a hole - which is why the bus is
                                      a replayable stream and not pub/sub.
     docker compose start statistics

  4  docker compose stop db           DO NOT demo this - say it instead. Login
                                      genuinely fails. Naming the one thing that
                                      does take you down is worth more than a
                                      fourth green demo.

  Two users, one shared price stream, different baselines:
     http://localhost:8080/?user=asha    http://localhost:8080/?user=ravi

  Note: this is a live free feed. Outside NSE hours (09:15-15:30 IST, Mon-Fri) prices
  do not move because nothing is trading, and during hours the feed runs ~15 minutes
  behind - the freshness chip says "delayed" because it is.
DEMO
}

cmd_reset() {
  info 'removing containers and volumes'
  "${COMPOSE[@]}" down --volumes --remove-orphans
  info 'done - the next start will re-seed'
}

usage() {
  sed -n '3,14p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
  printf 'Environment: WEB_PORT (%s)  API_PORT (%s)  PROVIDER (replay)  REPLAY_SPEED (30)\n' \
    "$WEB_PORT" "$API_PORT"
}

main() {
  local cmd="${1:-}"; [[ $# -gt 0 ]] && shift
  case "$cmd" in
    start)  preflight; cmd_start "$@" ;;
    stop)   preflight; cmd_stop ;;
    status) preflight; cmd_status ;;
    logs)   preflight; cmd_logs "$@" ;;
    test)   preflight; cmd_test ;;
    reset)  preflight; cmd_reset ;;
    demo)   cmd_demo ;;
    ''|-h|--help|help) usage ;;
    *) usage >&2; die "unknown command: $cmd" ;;
  esac
}

main "$@"
