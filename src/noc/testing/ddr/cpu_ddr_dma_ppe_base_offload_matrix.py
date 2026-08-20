#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
NOC_ROOT = HERE.parents[1]
REPO_ROOT = NOC_ROOT.parents[1]
DEFAULT_GEM5 = REPO_ROOT / "build" / "X86" / "gem5.opt"
TARGET = HERE / "cpu_ddr_dma_ppe_base_axis_sink_smoke.py"
OFFLOADS = ("none", "telemetry", "segmentation", "checksum", "nat")


def main():
    gem5_bin = Path(os.environ.get("GEM5_BIN", str(DEFAULT_GEM5))).resolve()
    if not gem5_bin.exists():
        print(f"missing gem5 binary: {gem5_bin}", file=sys.stderr)
        return 2

    failures = []
    for offload in OFFLOADS:
        env = os.environ.copy()
        env["PPE_OFFLOAD"] = offload
        cmd = [str(gem5_bin), str(TARGET)]
        print(f"== CPU PPE offload smoke: {offload} ==")
        proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
        if proc.returncode != 0:
            failures.append((offload, proc.returncode))

    print("== CPU PPE offload matrix summary ==")
    if not failures:
        for offload in OFFLOADS:
            print(f"{offload}: PASS")
        return 0

    for offload in OFFLOADS:
        match = next((code for name, code in failures if name == offload), None)
        if match is None:
            print(f"{offload}: PASS")
        else:
            print(f"{offload}: FAIL ({match})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
