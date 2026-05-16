#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "warning: scripts/deploy_local_intentmux.sh is deprecated; use scripts/rollout_compose_intentmux.sh" >&2
exec "${script_dir}/rollout_compose_intentmux.sh" "$@"
