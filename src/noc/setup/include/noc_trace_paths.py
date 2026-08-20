import os
from pathlib import Path


# Simulation/runtime CSV output (traffic monitor, NPS traces, flit trace, metrics).
NOC_CSV_OUTPUT_DIR = Path(
    os.environ.get(
        "NOC_CSV_OUTPUT_DIR",
        os.environ.get("NOC_RUNTIME_ARTIFACT_DIR", "src/noc/out/csv"),
    )
)
# Post-run matplotlib PNG output from noc_graphs and standalone plot scripts.
NOC_GRAPH_OUTPUT_DIR = Path(
    os.environ.get("NOC_GRAPH_OUTPUT_DIR", "src/noc/out/graphs")
)

# Backward-compatible alias for trace writers.
RUNTIME_TRACE_ARTIFACT_DIR = NOC_CSV_OUTPUT_DIR

NPS_QUEUE_TRACE_FILENAME = "nps_queue_trace.csv"
NPS_OCC_TRACE_FILENAME = "nps_occ_all.csv"
NPS_FLIT_TRACE_FILENAME = "nps_flit_trace.csv"
NSU_READ_DRAIN_TRACE_FILENAME = "nsu_read_drain_trace.csv"


def noc_csv_output_dir() -> str:
    return os.fspath(NOC_CSV_OUTPUT_DIR)


def noc_graph_output_dir() -> str:
    return os.fspath(NOC_GRAPH_OUTPUT_DIR)


def runtime_trace_artifact_dir() -> str:
    return noc_csv_output_dir()


def runtime_trace_artifact_path(filename: str) -> str:
    return os.fspath(NOC_CSV_OUTPUT_DIR / filename)


def noc_graph_output_path(filename: str) -> str:
    return os.fspath(NOC_GRAPH_OUTPUT_DIR / filename)


def ensure_runtime_trace_artifact_dir() -> str:
    NOC_CSV_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return noc_csv_output_dir()


def ensure_noc_graph_output_dir() -> str:
    NOC_GRAPH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return noc_graph_output_dir()
