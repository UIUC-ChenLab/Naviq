"""Legacy wrapper for the moved DDR CPU DMA config module."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_TARGET = Path(__file__).resolve().parents[2] / "ddr" / "setup" / "noc_cpu_ddr_dma_config.py"
_SPEC = spec_from_file_location("_noc_cpu_ddr_dma_config_impl", _TARGET)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load legacy wrapper target: {_TARGET}")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

for _name in dir(_MODULE):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_MODULE, _name)

del Path
del module_from_spec
del spec_from_file_location
del _TARGET
del _SPEC
del _MODULE
del _name
