#!/usr/bin/env bash
# Extra compose files for this machine. They only matter for vLLM, which never starts unless
# LLM=1 is given (make osmc-rag-up LLM=1). Without LLM=1 this prints nothing and does nothing.
# Prints nothing when there is no GPU either.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ "${LLM:-0}" != "1" ]; then
  exit 0
fi
if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi -L >/dev/null 2>&1; then
  exit 0
fi
# nvidia-smi can work while CUDA does not (after suspend/resume cuInit returns 999 until the
# driver is reloaded). vLLM then crashes on start, so fall back to the CPU image.
if ! python3 -c 'import ctypes,sys; sys.exit(ctypes.CDLL("libcuda.so.1").cuInit(0))' >/dev/null 2>&1; then
  echo "osmc/compose-files.sh: CUDA does not initialise, vLLM runs on the CPU" >&2
  exit 0
fi
"$here/prepare-nvidia-libs.sh"
"$here/prepare-cuda13-libs.sh"
# Naming any -f turns off the default docker-compose.yml, so list both.
printf '%s\n' "-f docker-compose.yml -f osmc/gpu.yml"
