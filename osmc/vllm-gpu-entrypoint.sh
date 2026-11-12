#!/usr/bin/env bash
# Register the host driver libraries, then start vLLM.
set -euo pipefail
if [ -d /opt/nvidia ]; then
  echo /opt/nvidia >/etc/ld.so.conf.d/nvidia-host.conf
  ldconfig
fi
exec "$@"
