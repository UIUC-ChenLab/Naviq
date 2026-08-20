import sys
import importlib.util
from pathlib import Path


def run_generic_smoke(default_args, label):
    setup_dir = Path(__file__).resolve().parents[2] / "setup"
    setup_dir_str = str(setup_dir)
    if setup_dir_str not in sys.path:
        sys.path.insert(0, setup_dir_str)

    sys.argv = [sys.argv[0], *default_args, *sys.argv[1:]]
    print(f"[{label}] argv={' '.join(sys.argv[1:])}")

    import noc_config  # noqa: F401


def run_script_smoke(script_rel_path, default_args, label):
    sys.argv = [sys.argv[0], *default_args, *sys.argv[1:]]
    print(f"[{label}] argv={' '.join(sys.argv[1:])}")

    script_path = Path(__file__).resolve().parents[4] / script_rel_path
    module_name = f"generic_smoke_{Path(script_rel_path).stem}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load smoke script from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
