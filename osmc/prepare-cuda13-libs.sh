#!/usr/bin/env bash
# vLLM 0.32's torchcodec is linked against CUDA 13 sonames. The published
# cu129 image only ships CUDA 12.9, so pull the matching 13.0 runtime libs
# (this driver reports CUDA 13.0).
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
dest="$here/.cuda13-libs"
if [ -s "$dest/libnvrtc.so.13" ] && [ -s "$dest/libcudart.so.13" ]; then
  exit 0
fi

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT
curl -fsSL -o "$tmpdir/runtime.whl" \
  'https://files.pythonhosted.org/packages/2e/24/d1558f3b68b1d26e706813b1d10aa1d785e4698c425af8db8edc3dced472/nvidia_cuda_runtime-13.0.96-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl'
curl -fsSL -o "$tmpdir/nvrtc.whl" \
  'https://files.pythonhosted.org/packages/c3/68/483a78f5e8f31b08fb1bb671559968c0ca3a065ac7acabfc7cee55214fd6/nvidia_cuda_nvrtc-13.0.88-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl'

mkdir -p "$dest"
python3 - "$tmpdir" "$dest" <<'PY'
import pathlib, sys, zipfile
src, dest = map(pathlib.Path, sys.argv[1:])
for whl in src.glob("*.whl"):
    with zipfile.ZipFile(whl) as z:
        for name in z.namelist():
            if "/lib/" in name and (name.endswith(".so") or ".so." in name):
                (dest / pathlib.Path(name).name).write_bytes(z.read(name))
PY
test -s "$dest/libnvrtc.so.13"
test -s "$dest/libcudart.so.13"
