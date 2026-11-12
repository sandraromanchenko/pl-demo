#!/usr/bin/env bash
# Copy the host NVIDIA driver libraries into osmc/.nvidia-libs so a
# container can see the GPU without nvidia-container-toolkit.
# Hardlinks are not possible: the libraries are owned by root.
set -euo pipefail

if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi -L >/dev/null 2>&1; then
  exit 0
fi

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
dest="$here/.nvidia-libs"
cuda=/usr/lib/x86_64-linux-gnu/libcuda.so.1
if [ ! -e "$cuda" ]; then
  echo "osmc/prepare-nvidia-libs.sh: $cuda is missing" >&2
  exit 1
fi

ver=$(basename "$(readlink -f "$cuda")")
ver=${ver#libcuda.so.}
major=${ver%%.*}
pkg="libnvidia-compute-${major}:amd64"
if ! dpkg -L "$pkg" >/dev/null 2>&1; then
  echo "osmc/prepare-nvidia-libs.sh: package $pkg is not installed" >&2
  exit 1
fi

mkdir -p "$dest"
find "$dest" -mindepth 1 -delete
while IFS= read -r f; do
  [ -e "$f" ] || continue
  base=$(basename "$f")
  if [ -L "$f" ]; then
    ln -s "$(readlink "$f")" "$dest/$base"
  else
    cp -a "$f" "$dest/$base"
  fi
done < <(dpkg -L "$pkg" | awk '/\.so/ && !/i386/')

test -e "$dest/libcuda.so.1"
test -e "$dest/libnvidia-ml.so.1"
