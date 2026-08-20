#!/usr/bin/env python3
"""Run the deterministic AXI-MM handshake-stress experiment."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[6]
SMOKE_SCRIPT = "src/noc/testing/generic/aximm_handshake_stress_smoke.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--gem5",
        type=Path,
        default=REPO_ROOT / "build/NULL/gem5.opt",
        help="gem5 executable (default: build/NULL/gem5.opt)",
    )
    args = parser.parse_args()

    gem5 = args.gem5.resolve()
    if not gem5.is_file():
        parser.error(f"gem5 executable does not exist: {gem5}")

    output = args.output.resolve()
    command = [str(gem5), f"--outdir={output}", "tests/gem5/noc/run_noc_smoke.py", SMOKE_SCRIPT]
    print("Command:", " ".join(command))
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
