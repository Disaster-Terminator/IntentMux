#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/rollout_compose_intentmux.sh [options]

Manually roll out an IntentMux sidecar managed by Docker Compose.

Options:
  --dry-run              Print planned commands without running them.
  --verbose              Stream full command output to the terminal.
  --yes                  Confirm that this command may restart the IntentMux service.
  --allow-dirty          Allow rollout from a dirty git worktree.
  --skip-tests           Skip pytest. Route contract and preflight still run.
  --sync-runtime-config  Back up INTENTMUX_RUNTIME_CONFIG and copy config/routes.yaml.
  --ready-timeout SEC    Max seconds to wait for /ready and container health. Default: 60
  -h, --help             Show this help.

Environment:
  INTENTMUX_COMPOSE_FILE       Compose file. Default: examples/docker-compose.yml
  INTENTMUX_SERVICE            Compose service. Default: intentmux
  INTENTMUX_BASE_URL           Sidecar URL. Default: http://127.0.0.1:4001
  INTENTMUX_RUNTIME_CONFIG     Runtime routes.yaml, required only with --sync-runtime-config
  INTENTMUX_SOURCE_CONFIG      Source routes.yaml. Default: config/routes.yaml
  INTENTMUX_API_KEY            Optional inbound API key for preflight.
  ROUTER_INBOUND_API_KEY       Fallback inbound API key when INTENTMUX_API_KEY is unset.
  INTENTMUX_READY_TIMEOUT      Wait timeout in seconds. Default: 60
  INTENTMUX_ROLLOUT_LOG_DIR    Command log directory. Default: .intentmux-home/logs/rollouts
EOF
}

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${INTENTMUX_COMPOSE_FILE:-${repo_dir}/examples/docker-compose.yml}"
service="${INTENTMUX_SERVICE:-intentmux}"
base_url="${INTENTMUX_BASE_URL:-http://127.0.0.1:4001}"
runtime_config="${INTENTMUX_RUNTIME_CONFIG:-}"
source_config="${INTENTMUX_SOURCE_CONFIG:-${repo_dir}/config/routes.yaml}"
api_key="${INTENTMUX_API_KEY:-${ROUTER_INBOUND_API_KEY:-}}"
dry_run=0
confirmed=0
allow_dirty=0
skip_tests=0
sync_runtime_config=0
ready_timeout="${INTENTMUX_READY_TIMEOUT:-60}"
verbose=0
rollout_log_dir="${INTENTMUX_ROLLOUT_LOG_DIR:-${repo_dir}/.intentmux-home/logs/rollouts}"
rollout_log="${rollout_log_dir}/intentmux-rollout-$(date +%Y%m%d-%H%M%S).log"

while (($#)); do
  case "$1" in
    --dry-run)
      dry_run=1
      ;;
    --verbose)
      verbose=1
      ;;
    --yes)
      confirmed=1
      ;;
    --allow-dirty)
      allow_dirty=1
      ;;
    --skip-tests)
      skip_tests=1
      ;;
    --sync-runtime-config)
      sync_runtime_config=1
      ;;
    --ready-timeout)
      shift
      if (($# == 0)); then
        echo "--ready-timeout requires a value" >&2
        exit 2
      fi
      ready_timeout="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

log() {
  printf '[intentmux-rollout] %s\n' "$*"
}

quote_args() {
  printf '%q ' "$@"
  printf '\n'
}

run() {
  if ((dry_run)); then
    printf '+ '
    quote_args "$@"
    return 0
  fi
  log "run: $(quote_args "$@")"
  if ((verbose)); then
    "$@" 2>&1 | tee -a "$rollout_log"
    return "${PIPESTATUS[0]}"
  fi
  {
    printf '+ '
    quote_args "$@"
    "$@"
  } >>"$rollout_log" 2>&1 || {
    local status=$?
    echo "command failed with exit ${status}: $(quote_args "$@")" >&2
    echo "last 80 log lines from ${rollout_log}:" >&2
    tail -80 "$rollout_log" >&2 || true
    return "$status"
  }
}

run_labeled() {
  local label="$1"
  shift
  if ((dry_run)); then
    printf '+ %s\n' "$label"
    return 0
  fi
  log "run: $label"
  if ((verbose)); then
    {
      printf '+ %s\n' "$label"
      "$@"
    } 2>&1 | tee -a "$rollout_log"
    return "${PIPESTATUS[0]}"
  fi
  {
    printf '+ %s\n' "$label"
    "$@"
  } >>"$rollout_log" 2>&1 || {
    local status=$?
    echo "command failed with exit ${status}: ${label}" >&2
    echo "last 80 log lines from ${rollout_log}:" >&2
    tail -80 "$rollout_log" >&2 || true
    return "$status"
  }
}

wait_for_ready() {
  local url="${base_url}/ready"
  log "wait for ${url}"
  if ((dry_run)); then
    return 0
  fi
  local deadline=$((SECONDS + ready_timeout))
  while ((SECONDS <= deadline)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      curl -fsS "$url"
      printf '\n'
      return 0
    fi
    sleep 1
  done
  echo "timed out waiting for ${url}" >&2
  return 1
}

wait_for_container_healthy() {
  log "wait for container ${service} to become healthy"
  if ((dry_run)); then
    return 0
  fi
  local deadline=$((SECONDS + ready_timeout))
  local status=""
  while ((SECONDS <= deadline)); do
    status="$(docker ps --filter "name=${service}" --format "{{.Status}}" | head -n 1)"
    if [[ "$status" == *"(healthy)"* ]]; then
      docker ps --filter "name=${service}" --format "{{.Names}} {{.Status}}"
      return 0
    fi
    if [[ -n "$status" && "$status" != *"(health: starting)"* ]]; then
      docker ps --filter "name=${service}" --format "{{.Names}} {{.Status}}"
    fi
    sleep 1
  done
  echo "timed out waiting for healthy container ${service}; last status: ${status:-missing}" >&2
  return 1
}

require_file() {
  local path="$1"
  local name="$2"
  if [[ ! -f "$path" ]]; then
    echo "$name not found: $path" >&2
    exit 1
  fi
}

if ((dry_run == 0 && confirmed == 0)); then
  echo "refusing to restart ${service}; pass --yes to confirm this rollout may restart IntentMux" >&2
  exit 1
fi

mkdir -p "$rollout_log_dir"

preflight_cmd=(uv run python scripts/preflight.py --router-base-url "$base_url")
if [[ -n "$api_key" ]]; then
  preflight_cmd+=(--intentmux-api-key "$api_key")
fi
legacy_preflight_cmd=("${preflight_cmd[@]}" --model semantic-router)
canonical_preflight_cmd=("${preflight_cmd[@]}" --model auto)

log "repo: $repo_dir"
log "compose file: $compose_file"
log "service: $service"
log "base url: $base_url"
log "rollout log: $rollout_log"
if ((verbose)); then
  log "verbose command output enabled"
fi

cd "$repo_dir"
require_file "$compose_file" "INTENTMUX_COMPOSE_FILE"
require_file "$source_config" "INTENTMUX_SOURCE_CONFIG"
if ((sync_runtime_config)) && [[ -z "$runtime_config" ]]; then
  echo "INTENTMUX_RUNTIME_CONFIG is required when --sync-runtime-config is used" >&2
  exit 1
fi

current_commit="$(git rev-parse --short HEAD)"
log "git commit: $current_commit"

if [[ -n "$(git status --short)" ]]; then
  log "git worktree is dirty"
  if ((allow_dirty == 0)); then
    echo "refusing to roll out from a dirty worktree; pass --allow-dirty to override" >&2
    exit 1
  fi
else
  log "git worktree is clean"
fi

if ((skip_tests == 0)); then
  run uv run pytest -q
else
  log "skipping pytest by request"
fi
run uv run python scripts/verify_route_contract.py
wait_for_ready
run "${legacy_preflight_cmd[@]}"

if ((sync_runtime_config)); then
  require_file "$runtime_config" "INTENTMUX_RUNTIME_CONFIG"
  backup="${runtime_config}.backup-$(date +%Y%m%d-%H%M%S)"
  log "sync runtime config: $source_config -> $runtime_config"
  run cp "$runtime_config" "$backup"
  run cp "$source_config" "$runtime_config"
fi

run docker compose -f "$compose_file" build "$service"
run docker compose -f "$compose_file" up -d "$service"
wait_for_ready
wait_for_container_healthy
run "${canonical_preflight_cmd[@]}"

cost_first_payload='{"model":"auto","messages":[{"role":"user","content":"summarize this tool schema"}],"tools":[{"type":"function","function":{"name":"read_file","description":"read a file","parameters":{"type":"object","properties":{}}}}],"tool_choice":"auto"}'
cost_first_cmd=(uv run python -c 'import json, sys, urllib.request; url=sys.argv[1]+"/v1/semantic-router/decision"; payload=sys.argv[2].encode(); req=urllib.request.Request(url,data=payload,headers={"Content-Type":"application/json"}); data=json.loads(urllib.request.urlopen(req,timeout=30).read()); print(json.dumps(data,ensure_ascii=False)); assert data.get("policy_id")!="agent_signal"; assert data.get("route_id")=="lite"' "$base_url" "$cost_first_payload")
run_labeled "cost-first decision smoke" "${cost_first_cmd[@]}"

if ((dry_run)); then
  log "dry run completed for commit $current_commit"
else
  log "rollout checks completed for commit $current_commit"
fi
