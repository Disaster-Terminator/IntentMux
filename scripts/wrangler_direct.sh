#!/usr/bin/env bash
set -euo pipefail

# Run Wrangler without inheriting local proxy variables. This keeps Cloudflare
# CLI probes quiet when direct connectivity works.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
unset http_proxy https_proxy all_proxy no_proxy

exec wrangler "$@"
