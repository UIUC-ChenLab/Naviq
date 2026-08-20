import os
import runpy
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
TARGET = THIS_DIR / "cpu_ddr_dma_ppe_base_axis_sink_smoke.py"


os.environ["PPE_OFFLOAD"] = "checksum"
runpy.run_path(str(TARGET), run_name="__main__")
