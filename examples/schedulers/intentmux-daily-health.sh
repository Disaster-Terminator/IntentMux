#!/usr/bin/env sh
set -eu

# Generic scheduler wrapper for cron, systemd timers, CI, or private ops agents.
# Copy this file into your scheduler-owned location and adjust environment
# variables there. Do not commit deployment-specific job IDs, notification
# targets, secrets, or machine-specific absolute paths.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INTENTMUX_REPO=${INTENTMUX_REPO:-$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)}
INTENTMUX_HOME=${INTENTMUX_HOME:-"$INTENTMUX_REPO/.intentmux-home"}
INTENTMUX_LOG_DIR=${INTENTMUX_LOG_DIR:-"$INTENTMUX_HOME/logs"}
INTENTMUX_ROUTER_BASE_URL=${INTENTMUX_ROUTER_BASE_URL:-http://127.0.0.1:4001}
INTENTMUX_LITELLM_BASE_URL=${INTENTMUX_LITELLM_BASE_URL:-http://127.0.0.1:4000}
INTENTMUX_LOG_CONTAINER=${INTENTMUX_LOG_CONTAINER:-intentmux}
INTENTMUX_MIN_ROUTE_RECORDS=${INTENTMUX_MIN_ROUTE_RECORDS:-0}
INTENTMUX_TIMEZONE=${INTENTMUX_TIMEZONE:-Asia/Shanghai}

exec uv --directory "$INTENTMUX_REPO" run python scripts/intentmux_daily_health.py \
  --repo "$INTENTMUX_REPO" \
  --log-dir "$INTENTMUX_LOG_DIR" \
  --router-base-url "$INTENTMUX_ROUTER_BASE_URL" \
  --litellm-base-url "$INTENTMUX_LITELLM_BASE_URL" \
  --timezone "$INTENTMUX_TIMEZONE" \
  --min-route-records "$INTENTMUX_MIN_ROUTE_RECORDS" \
  --log-container "$INTENTMUX_LOG_CONTAINER"
