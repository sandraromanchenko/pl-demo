#!/usr/bin/env bash
# Block until each AWS host has finished its user_data bootstrap.
#
# user_data does `rm -rf /opt/pl-demo` before cloning, so a demo command that
# lands mid-bootstrap fails with either a missing directory or a docker pull
# racing the one cloud-init is already running. No-op without demo/aws.env.

set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# shellcheck source=/dev/null
. "$here/lib.sh"
if [ -f "$here/aws.env" ]; then
  # shellcheck source=/dev/null
  . "$here/aws.env"
fi

host_for() {
  case "$1" in
    data) echo "${DEMO_HOST_DATA:-}" ;;
    models) echo "${DEMO_HOST_MODELS:-}" ;;
    app) echo "${DEMO_HOST_APP:-}" ;;
  esac
}

seen=""
waited=0

for role in data models app; do
  host=$(host_for "$role")
  [ -n "$host" ] || continue

  case " $seen " in
    *" $host "*) continue ;;
  esac
  seen="$seen $host"
  waited=1

  echo "-> waiting for cloud-init on $(demo_role_label "$role") (first boot: several minutes)"

  # `cloud-init status --wait` returns 2 on a recoverable-error finish, which
  # still means bootstrap is done; only a hard failure should stop the demo.
  status=0
  ssh ${DEMO_SSH_OPTS:--o StrictHostKeyChecking=accept-new} "$host" \
    'cloud-init status --wait >/dev/null; cloud-init status --long' || status=$?

  if [ "$status" -eq 1 ]; then
    echo "   cloud-init FAILED on $(demo_role_label "$role"); check /var/log/cloud-init-output.log" >&2
    exit 1
  fi

  ssh ${DEMO_SSH_OPTS:--o StrictHostKeyChecking=accept-new} "$host" \
    "test -d ${DEMO_REMOTE_DIR:-/opt/pl-demo}" || {
    echo "   ${DEMO_REMOTE_DIR:-/opt/pl-demo} missing on $(demo_role_label "$role") after bootstrap" >&2
    exit 1
  }
done

if [ "$waited" -eq 0 ]; then
  echo "local compose project: nothing to wait for"
else
  echo "all hosts bootstrapped"
fi
