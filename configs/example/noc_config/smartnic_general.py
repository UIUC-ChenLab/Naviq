import runpy
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[3]
SCRIPT_PATH = REPO_ROOT / "src" / "noc" / "smartnic" / "smartnic_general.py"
MAIN_DIR = REPO_ROOT / "src" / "noc" / "smartnic"
CONFIGS_DIR = REPO_ROOT / "configs"

for path in (CONFIGS_DIR, MAIN_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
