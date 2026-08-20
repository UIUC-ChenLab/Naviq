import os
import runpy
from pathlib import Path


HERE = Path(__file__).resolve().parent
TARGET = HERE / "cpu_ddr_dma_ppe_base_axis_sink_smoke.py"

os.environ["PPE_OFFLOAD"] = "nat"
runpy.run_path(str(TARGET), run_name="__main__")
