#!/usr/bin/env bash
# Start/stop the AgriSage dev server plus a public Cloudflare quick tunnel.
#
#   ./scripts/demo.sh start     # run the server + open a public HTTPS URL
#   ./scripts/demo.sh stop      # shut both down
#   ./scripts/demo.sh status    # what's running, and the current URL
#   ./scripts/demo.sh url       # print the public URL only
#   ./scripts/demo.sh logs      # tail both log files
#
# Notes
#   - The public URL changes every time the tunnel restarts (free quick
#     tunnels get a random hostname), so re-share it after each start.
#   - OPENAI_API_KEY and a 32-byte-or-longer JWT_SECRET are read from .env.
#   - PORT=5001 ./scripts/demo.sh start  runs a second instance elsewhere.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-5000}"
RUN_DIR="${TMPDIR:-/tmp}/agrisage-demo-$PORT"
SERVER_LOG="$RUN_DIR/server.log"
TUNNEL_LOG="$RUN_DIR/tunnel.log"
SERVER_PID="$RUN_DIR/server.pid"
TUNNEL_PID="$RUN_DIR/tunnel.pid"

export MODEL_CHECKPOINT_PATH="${MODEL_CHECKPOINT_PATH:-backend/models/weights/classification_model.pth}"
export MODEL_CONFIG_PATH="${MODEL_CONFIG_PATH:-backend/models/config6.json}"
# A Cloud SQL DATABASE_URL may be present in .env for deployment. The local
# demo deliberately overrides it with a disposable/local SQLite database.
export DATABASE_URL="${LOCAL_DATABASE_URL:-sqlite+pysqlite:///$REPO/backend/db/agrisage.db}"

find_python() {
  for p in "${AGRISAGE_PYTHON:-}" \
           "/home/kntst/anaconda3/envs/env1/bin/python" \
           "$REPO/.venv/bin/python" \
           "$(command -v python3 || true)"; do
    [ -n "$p" ] && [ -x "$p" ] && { echo "$p"; return; }
  done
  echo "no python found (need torch + cv2 — see backend/models/CLAUDE.md)" >&2
  exit 1
}

find_cloudflared() {
  for c in "$(command -v cloudflared || true)" "$HOME/.local/bin/cloudflared"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return; }
  done
  echo ""
}

alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

# PID listening on $PORT — lets stop/status target this instance only, so a
# second instance on another port is never touched.
port_pid() { ss -lptnH "sport = :$PORT" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2; }

# Our tunnel process, matched on the port it forwards (other args vary).
tunnel_pid() { pgrep -af "cloudflared tunnel" 2>/dev/null | grep -E "localhost:$PORT(\s|$)" | head -1 | cut -d' ' -f1; }

public_url() { grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -1; }

start() {
  mkdir -p "$RUN_DIR"
  if alive "$SERVER_PID"; then
    echo "server already running (pid $(cat "$SERVER_PID")) on port $PORT"
  else
    local py; py="$(find_python)"
    echo "starting server on port $PORT  ($py)"
    ( cd "$REPO" && PORT="$PORT" nohup "$py" backend/app.py >"$SERVER_LOG" 2>&1 & echo $! >"$SERVER_PID" )
    for _ in $(seq 30); do
      curl -sf -o /dev/null "http://localhost:$PORT/" && break
      sleep 1
    done
    if ! curl -sf -o /dev/null "http://localhost:$PORT/"; then
      echo "server failed to start — last lines of $SERVER_LOG:" >&2
      tail -15 "$SERVER_LOG" >&2
      exit 1
    fi
  fi
  echo "local:  http://localhost:$PORT"

  local cf; cf="$(find_cloudflared)"
  if [ -z "$cf" ]; then
    echo "cloudflared not installed — local only. To install:"
    echo "  curl -sL -o ~/.local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x ~/.local/bin/cloudflared"
    return
  fi
  if alive "$TUNNEL_PID"; then
    echo "public: $(public_url)  (tunnel already running)"
    return
  fi
  echo "opening public tunnel..."
  nohup "$cf" tunnel --url "http://localhost:$PORT" --no-autoupdate >"$TUNNEL_LOG" 2>&1 &
  echo $! >"$TUNNEL_PID"
  for _ in $(seq 30); do
    [ -n "$(public_url)" ] && break
    sleep 1
  done
  local url; url="$(public_url)"
  if [ -z "$url" ]; then
    echo "tunnel did not report a URL — see $TUNNEL_LOG" >&2
    return
  fi
  # A fresh hostname needs ~10s before it serves traffic (this WSL blocks QUIC,
  # so cloudflared falls back to HTTP/2 and takes a bit longer to come up).
  # Wait so the URL is actually usable the moment it's printed and shared.
  local ready=0
  for _ in $(seq 20); do
    if curl -sf -o /dev/null --max-time 5 "$url/"; then ready=1; break; fi
    sleep 2
  done
  if [ "$ready" = 1 ]; then
    echo "public: $url"
  else
    echo "public: $url  (not responding yet — give it a few more seconds)"
  fi
}

stop() {
  local stopped=0 tpid
  alive "$TUNNEL_PID" && { kill "$(cat "$TUNNEL_PID")" 2>/dev/null && stopped=1; }
  tpid="$(tunnel_pid)"
  [ -n "$tpid" ] && { kill "$tpid" 2>/dev/null && stopped=1; }
  rm -f "$TUNNEL_PID"

  # Flask's reloader forks a child that keeps the socket, so kill whatever
  # still holds the port until it's actually free rather than one pid once.
  alive "$SERVER_PID" && { kill "$(cat "$SERVER_PID")" 2>/dev/null && stopped=1; }
  for _ in $(seq 10); do
    local spid; spid="$(port_pid)"
    [ -z "$spid" ] && break
    kill "$spid" 2>/dev/null && stopped=1
    sleep 1
  done
  rm -f "$SERVER_PID"

  if [ -n "$(port_pid)" ]; then
    echo "warning: something still holds port $PORT (pid $(port_pid)) — kill -9 it manually" >&2
  fi
  [ "$stopped" = 1 ] && echo "stopped (port $PORT)." || echo "nothing was running on port $PORT."
}

status() {
  local spid tpid
  spid="$(port_pid)"
  if [ -n "$spid" ]; then echo "server: running (pid $spid) http://localhost:$PORT"
  else echo "server: stopped"; fi

  tpid="$(tunnel_pid)"
  if [ -n "$tpid" ]; then
    local url; url="$(public_url)"
    echo "tunnel: running (pid $tpid) ${url:-URL unknown — started outside this script}"
  else echo "tunnel: stopped"; fi
}

case "${1:-}" in
  start)  start ;;
  stop)   stop ;;
  restart) stop; start ;;
  status) status ;;
  url)    public_url ;;
  logs)   tail -f "$SERVER_LOG" "$TUNNEL_LOG" ;;
  *) echo "usage: $0 {start|stop|restart|status|url|logs}"; exit 1 ;;
esac
