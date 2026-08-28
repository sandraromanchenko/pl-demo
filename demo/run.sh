#!/usr/bin/env bash
# Run one command for one demo role, locally or over SSH on the AWS host

set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(dirname "$here")

# shellcheck source=/dev/null
. "$here/lib.sh"
# aws.env overrides the environment, so DEMO_LOCAL=1 is the way to force a local
# run without deleting a generated aws.env.
if [ "${DEMO_LOCAL:-0}" != "1" ] && [ -f "$here/aws.env" ]; then
  # shellcheck source=/dev/null
  . "$here/aws.env"
fi

role=${1:-}
shift || true
cmd="$*"
if [ -z "$role" ] || [ -z "$cmd" ]; then
  echo "usage: demo/run.sh <data|models|app> <command...>" >&2
  exit 2
fi

case "$role" in
  data) host=${DEMO_HOST_DATA:-} ;;
  models) host=${DEMO_HOST_MODELS:-} ;;
  app) host=${DEMO_HOST_APP:-} ;;
  *)
    echo "demo/run.sh: unknown role '$role' (data|models|app)" >&2
    exit 2
    ;;
esac

if [ "${DEMO_QUIET:-0}" != "1" ]; then
  echo "-> $(demo_role_label "$role")" >&2
fi

if [ -z "$host" ]; then
  cd "$repo"
  exec bash -c "$cmd"
fi

remote_dir=${DEMO_REMOTE_DIR:-/opt/pl-demo}

# ConnectTimeout goes last so DEMO_SSH_OPTS can override it (ssh takes the first
# value for an option). Without it, a terminated instance drops packets and ssh
# hangs with no output, which looks exactly like a slow local run.
exec ssh ${DEMO_SSH_OPTS:--o StrictHostKeyChecking=accept-new} \
  -o ConnectTimeout="${DEMO_SSH_CONNECT_TIMEOUT:-10}" "$host" \
  "cd $remote_dir 2>/dev/null || { echo \"demo/run.sh: $remote_dir not there yet - user_data still bootstrapping? wait with: make demo-wait\" >&2; exit 1; }
   $cmd"
