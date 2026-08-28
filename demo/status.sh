#!/usr/bin/env bash
# What is running for the demo, one block per machine.
# Headers are role names only — Elastic IPs stay off the projector.

set -euo pipefail

# shellcheck source=/dev/null
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

demo_run_all_nopause 'docker compose ps'
