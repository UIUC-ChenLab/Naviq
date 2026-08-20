#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

targets=(
  build/NULL/noc/noc_write_structs.test.opt
  build/NULL/noc/noc_mm_write_depacketizer.test.opt
  build/NULL/noc/noc_axis_depacketizer.test.opt
  build/NULL/noc/noc_rrob.test.opt
)

scons "${targets[@]}" -j8

for target in "${targets[@]}"; do
  "./${target}"
done
