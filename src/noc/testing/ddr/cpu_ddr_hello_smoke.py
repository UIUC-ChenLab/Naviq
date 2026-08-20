import runpy
import sys
from pathlib import Path


MAIN_DIR = Path(__file__).resolve().parents[1]
NOC_ROOT = MAIN_DIR.parents[0]
REPO_ROOT = NOC_ROOT.parents[1]
LEGACY_SETUP_DIR = NOC_ROOT / "setup" / "legacy"
if str(LEGACY_SETUP_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_SETUP_DIR))


TOPOLOGY = "src/noc/topology/topologies/1nmu_to_ddr"
BINARY = REPO_ROOT / "tests" / "test-progs" / "hello" / "bin" / "x86" / "linux" / "hello"


def add_default_arg(flag, value):
    if not any(arg == flag or arg.startswith(flag + "=") for arg in sys.argv[1:]):
        sys.argv.extend([flag, str(value)])


add_default_arg("--noc-topology", TOPOLOGY)
add_default_arg("--binary", BINARY)
add_default_arg("--num-cpus", 1)
add_default_arg("--abs-max-tick", 20000000000)

runpy.run_path(str(LEGACY_SETUP_DIR / "noc_config_cpu_test.py"), run_name="__main__")

print("[CPU DDR hello smoke] completed")
