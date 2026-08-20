import runpy
import os
import sys
from pathlib import Path

import m5


REPO_ROOT = Path(__file__).resolve().parents[3]


if len(sys.argv) < 2:
    raise RuntimeError("run_noc_smoke.py requires a smoke script path")

smoke_path = REPO_ROOT / sys.argv[1]
if not smoke_path.exists():
    raise RuntimeError(f"NoC smoke script does not exist: {smoke_path}")

os.environ.setdefault(
    "NOC_RUNTIME_ARTIFACT_DIR",
    str(Path(m5.options.outdir) / "noc-artifacts"),
)
os.chdir(REPO_ROOT)
sys.path.insert(0, str(smoke_path.parent))
sys.argv = [str(smoke_path)] + sys.argv[2:]
runpy.run_path(str(smoke_path), run_name="__m5_main__")
