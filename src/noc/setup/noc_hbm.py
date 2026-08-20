#!/usr/bin/env python3
"""
Generate an HBM N-TG topology bundle under hbm_1stack_16GB/<N>tg/ and optionally
run gem5 via noc_config.py.

Edit USER SETTINGS below, or pass CLI flags (e.g. --num-tg 3).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

# ---------------------------------------------------------------------------
# USER SETTINGS (defaults; overridden by CLI where noted)
# ---------------------------------------------------------------------------

NUM_TG = 4
RUN_SIMULATION = True
OVERWRITE_BUNDLE = True

# Repo-relative paths
GEM5_BINARY = "build/NULL/gem5.debug"
NOC_CONFIG = "src/noc/setup/noc_config.py"
BUNDLE_PARENT = "src/noc/topology/topologies/hbm_1stack_16GB"
FULL_BUNDLE_DIR = "src/noc/topology/topologies/hbm_1stack_16GB/full"
FULL_STEM = "hbm_1stack_16GB"

# Traffic generator / HBM timing
ADDRESS_INCREMENT = 256
ADDRESS_WRAP_BYTES = 16384
TRANSACTION_SIZE_BYTES = 512
BEAT_SIZE_BYTES = 32
MAX_WRITE_COMMANDS = 1000
MAX_OUTSTANDING_WRITES = 32
TG_CLOCK_MHZ = 500
HBM_CLOCK_MHZ = 1600
HBM_ROW_MISS_LATENCY_CYCLES = 15
HBM_READ_LATENCY_CYCLES = 25
HBM_WRITE_LATENCY_CYCLES = 15
HBM_RESP_LATENCY_CYCLES = 4

# Simulation (passed to noc_config.py)
NUM_PACKETS = 1000
SIM_CYCLES = 0
ABS_MAX_TICK = 10_000_000_000

# Sweep/test output (32 TGs × 12.796875 GB/s = 409.5 GB/s full 1-stack)
THEORETICAL_FULL_STACK_GBPS = 409.5
THEORETICAL_PER_TG_GBPS = 12.796875
MAX_TG_PER_STACK = 32
RUN_TEST_CSV = "src/noc/out/csv/hbm_1stack_16GB_run_test_bw.csv"
RUN_TEST_GRAPH = "src/noc/out/graphs/hbm_1stack_16GB_run_test_bw.png"
RUN_TEST_LOG_DIR = "src/noc/out/log"

# Tracing (opts.json)
RECORD_MODE_INTERFACES = 0
RECORD_HBM = 0
RECORD_HBM_GAP_CYCLES = 100

# HBM model (conn.json hbm_settings)
HBM_NUM_PC = 16
HBM_SHARED_BW_MBPS = 25600
HBM_NMU_BW_MBPS = 12800
HBM_PAGE_POLICY = "open_page"

PC_ADDRESS_SPACE_BYTES = 268435456
WRITE_BW_RE = re.compile(r"Achieved Write BW\s*=\s*([0-9.]+)")

# ---------------------------------------------------------------------------


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "src" / "noc" / "setup" / "noc_config.py").is_file():
            return parent
    return here.parents[2]


def bundle_dir_for_num_tg(num_tg: int, root: Path) -> Path:
    if num_tg < 1 or num_tg > 32:
        raise ValueError(f"num_tg must be in [1, 32], got {num_tg}")
    return root / BUNDLE_PARENT / f"{num_tg}tg"


def bundle_stem(num_tg: int) -> str:
    return f"{num_tg}tg"


def _load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def build_port_address_map(nts_path: Path) -> dict[str, tuple[int, int]]:
    """Map NTS port keys (…/I_hbm_chnlN_PORTM) -> (base, size)."""
    nts = _load_json(nts_path)
    port_addrs: dict[str, tuple[int, int]] = {}
    for inst in nts.get("LogicalInstances", []):
        if inst.get("CompType") != "HBMMC":
            continue
        channel_name = "/".join(inst["Name"].split("/")[-2:])
        addresses = inst.get("SysAddresses", [])
        for port in inst.get("Ports", []):
            port_num = int(port.replace("PORT", ""))
            addr_idx = min(port_num // 2, len(addresses) - 1)
            base = int(addresses[addr_idx]["Base"], 16)
            size = int(addresses[addr_idx]["Size"], 16)
            port_addrs[f"{channel_name}_{port}"] = (base, size)
    return port_addrs


def _tg_to_hbm_port(num_tg: int) -> list[tuple[str, int, int]]:
    """Return (tg_id, controller, port) for each active TG."""
    rows = []
    for idx in range(num_tg):
        rows.append((f"hbm_sat_tg_{idx:02d}", idx // 4, idx % 4))
    return rows


def _port_nts_key(controller: int, port: int, port_addrs: dict) -> str:
    chnl = f"I_hbm_chnl{controller}"
    suffix = f"{chnl}_PORT{port}"
    for key in port_addrs:
        if key.endswith(suffix):
            return key
    raise KeyError(f"No NTS port entry ending with {suffix}")


def _apply_tg_address_params(params: dict, base: int) -> None:
    wrap = max(ADDRESS_WRAP_BYTES, TRANSACTION_SIZE_BYTES) - 1
    params["address_increment"] = ADDRESS_INCREMENT
    params["base_addr"] = base
    params["max_addr"] = base + wrap
    params["nsu_min_addrs"] = [base]
    params["nsu_address_spaces"] = [PC_ADDRESS_SPACE_BYTES]
    params["nsu_selection"] = "INTERLEAVE"


def build_connections_json(
    num_tg: int,
    full_conn_path: Path,
    port_addrs: dict[str, tuple[int, int]],
) -> dict:
    full = _load_json(full_conn_path)
    tg_template = deepcopy(full["components"]["hbm_sat_tg_00"])
    hbm_template = deepcopy(full["components"]["hbm0_port0"])

    keep: set[str] = set()
    components: dict = {}
    connections: list[dict] = []

    for tg_id, ctrl, port in _tg_to_hbm_port(num_tg):
        hbm_id = f"hbm{ctrl}_port{port}"
        keep.add(tg_id)
        keep.add(hbm_id)

        tg_def = deepcopy(tg_template)
        tg_def["params"]["clock_domain_mhz"] = TG_CLOCK_MHZ
        tg_def["params"]["beat_size_bytes"] = BEAT_SIZE_BYTES
        tg_def["params"]["min_transaction_size_bytes"] = TRANSACTION_SIZE_BYTES
        tg_def["params"]["max_transaction_size_bytes"] = TRANSACTION_SIZE_BYTES
        tg_def["params"]["max_write_commands"] = MAX_WRITE_COMMANDS
        tg_def["params"]["max_outstanding_writes"] = MAX_OUTSTANDING_WRITES
        tg_def["params"]["max_write_bandwidth_mbps"] = 0
        tg_def["params"]["max_read_bandwidth_mbps"] = 0
        tg_def["params"]["align_addresses"] = False

        nts_key = _port_nts_key(ctrl, port, port_addrs)
        base, _size = port_addrs[nts_key]
        _apply_tg_address_params(tg_def["params"], base)
        components[tg_id] = tg_def

        if hbm_id not in components:
            hbm_def = deepcopy(hbm_template)
            hbm_def["params"]["clock_domain_mhz"] = HBM_CLOCK_MHZ
            hbm_def["params"]["row_miss_latency_cycles"] = HBM_ROW_MISS_LATENCY_CYCLES
            hbm_def["params"]["read_latency_cycles"] = HBM_READ_LATENCY_CYCLES
            hbm_def["params"]["write_latency_cycles"] = HBM_WRITE_LATENCY_CYCLES
            hbm_def["params"]["resp_latency_cycles"] = HBM_RESP_LATENCY_CYCLES
            components[hbm_id] = hbm_def

        connections.append(
            {"from": f"{tg_id}.m_axi", "to": f"{hbm_id}.s_axi"}
        )

    hbm_settings = full.get(
        "hbm_settings",
        {
            "num_pc": HBM_NUM_PC,
            "shared_bw_MBps": HBM_SHARED_BW_MBPS,
            "nmu_bw_MBps": HBM_NMU_BW_MBPS,
            "page_policy": HBM_PAGE_POLICY,
        },
    )

    return {
        "kind": "naviq.connections",
        "version": 1,
        "name": f"hbm_full_1_stack_16GB_{num_tg}tg",
        "components": components,
        "connections": connections,
        "hbm_settings": hbm_settings,
    }


def build_placement_json(num_tg: int, full_place_path: Path) -> dict:
    full = _load_json(full_place_path)
    placements = full.get("placements", {})

    keep_endpoints: set[str] = set()
    for tg_id, ctrl, port in _tg_to_hbm_port(num_tg):
        keep_endpoints.add(f"{tg_id}.m_axi")
        keep_endpoints.add(f"hbm{ctrl}_port{port}.s_axi")

    filtered = {
        ep: loc
        for ep, loc in placements.items()
        if ep in keep_endpoints
    }
    missing = keep_endpoints - set(filtered)
    if missing:
        raise KeyError(
            f"Placement JSON missing endpoints for num_tg={num_tg}: {sorted(missing)}"
        )

    return {
        "kind": "naviq.placement",
        "version": 1,
        "placements": filtered,
    }


def build_opts_json(num_tg: int) -> dict:
    return {
        "description": (
            f"hbm_1stack_16GB_{num_tg}tg "
            f"(generated by src/noc/setup/noc_hbm.py)."
        ),
        "record_mode_interfaces": RECORD_MODE_INTERFACES,
        "record_hbm": RECORD_HBM,
        "record_hbm_gap_cycles": RECORD_HBM_GAP_CYCLES,
        "record_nps": 0,
        "record_nps_gap_cycles": 200,
        "noc_probes": [],
    }


def write_bundle(
    num_tg: int,
    root: Path,
    *,
    overwrite: bool = True,
) -> Path:
    full_dir = root / FULL_BUNDLE_DIR
    out_dir = bundle_dir_for_num_tg(num_tg, root)
    stem = bundle_stem(num_tg)

    if out_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"Bundle already exists (set OVERWRITE_BUNDLE=True): {out_dir}"
            )
    else:
        out_dir.mkdir(parents=True)

    nts_src = full_dir / f"{FULL_STEM}.nts"
    ncr_src = full_dir / f"{FULL_STEM}.ncr"
    conn_src = full_dir / f"{FULL_STEM}.conn.json"
    place_src = full_dir / f"{FULL_STEM}.place.json"

    for src, suffix in (
        (nts_src, ".nts"),
        (ncr_src, ".ncr"),
    ):
        shutil.copy2(src, out_dir / f"{stem}{suffix}")

    port_addrs = build_port_address_map(nts_src)
    conn = build_connections_json(num_tg, conn_src, port_addrs)
    place = build_placement_json(num_tg, place_src)
    opts = build_opts_json(num_tg)

    _write_json(out_dir / f"{stem}.conn.json", conn)
    _write_json(out_dir / f"{stem}.place.json", place)
    _write_json(out_dir / f"{stem}.opts.json", opts)

    print(f"[noc_hbm] Wrote bundle: {out_dir}")
    return out_dir


def build_gem5_command(
    root: Path,
    bundle_dir: Path,
    gem5_binary: str,
    extra_args: list[str] | None = None,
) -> list[str]:
    gem5 = root / gem5_binary
    noc_config = root / NOC_CONFIG
    if not gem5.is_file():
        raise FileNotFoundError(f"gem5 binary not found: {gem5}")
    if not noc_config.is_file():
        raise FileNotFoundError(f"noc_config not found: {noc_config}")

    cmd = [
        os.fspath(gem5),
        os.fspath(noc_config),
        "--noc-topology",
        os.fspath(bundle_dir),
        "--num-packets",
        str(NUM_PACKETS),
        "--abs-max-tick",
        str(ABS_MAX_TICK),
    ]
    if SIM_CYCLES > 0:
        cmd.extend(["--sim-cycles", str(SIM_CYCLES)])
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def run_simulation(cmd: list[str], root: Path) -> int:
    env = os.environ.copy()
    user_site = Path.home() / ".local/lib/python3.10/site-packages"
    if user_site.is_dir():
        env["PYTHONPATH"] = (
            f"{user_site}:{env['PYTHONPATH']}"
            if env.get("PYTHONPATH")
            else str(user_site)
        )

    print(f"[noc_hbm] Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=root, env=env)
    return proc.returncode


def _simulation_env() -> dict[str, str]:
    env = os.environ.copy()
    user_site = Path.home() / ".local/lib/python3.10/site-packages"
    if user_site.is_dir():
        env["PYTHONPATH"] = (
            f"{user_site}:{env['PYTHONPATH']}"
            if env.get("PYTHONPATH")
            else str(user_site)
        )
    env.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    return env


def _sum_achieved_write_bw_mb_s(text: str) -> float:
    return sum(float(match.group(1)) for match in WRITE_BW_RE.finditer(text))


def _plot_run_test_results(rows: list[dict[str, object]], output_path: Path) -> None:
    plottable = [
        row for row in rows
        if row["gem5_exit_code"] == 0 and row["aggregate_write_bw_MBps"] != ""
    ]
    if not plottable:
        print("[noc_hbm] No successful run_test rows to plot.")
        return

    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [int(row["num_tg"]) for row in plottable]
    y = [float(row["aggregate_write_bw_MBps"]) / 1000.0 for row in plottable]

    x_theory = list(range(1, MAX_TG_PER_STACK + 1))
    y_theory_per_tg = [n * THEORETICAL_PER_TG_GBPS for n in x_theory]

    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    ax.plot(
        x,
        y,
        color="C0",
        linewidth=2,
        marker="o",
        markersize=4,
        label="Simulated",
        zorder=3,
    )
    ax.plot(
        x_theory,
        y_theory_per_tg,
        color="C4",
        linestyle="--",
        linewidth=2,
        label=(
            f"Theoretical maximum for active TGs "
            f"({THEORETICAL_PER_TG_GBPS:g} GB/s per TG)"
        ),
        zorder=2,
    )
    ax.axhline(
        THEORETICAL_FULL_STACK_GBPS,
        color="C3",
        linestyle=":",
        linewidth=2,
        label="Theoretical maximum of full stack usage",
        zorder=1,
    )
    ax.axvline(
        MAX_TG_PER_STACK,
        color="C2",
        linestyle=":",
        linewidth=2,
        label="Maximum traffic generators for 1 stack",
        zorder=1,
    )
    ax.set_xlabel("Number of HBM Traffic Generators")
    ax.set_ylabel("Aggregate Write Bandwidth (GB/s)")
    ax.set_xticks(range(1, 33))
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    print(f"[noc_hbm] Wrote plot: {output_path}")


def run_test_sweep(
    root: Path,
    gem5_binary: str,
    extra_args: list[str] | None = None,
) -> int:
    csv_path = root / RUN_TEST_CSV
    graph_path = root / RUN_TEST_GRAPH
    log_dir = root / RUN_TEST_LOG_DIR
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    env = _simulation_env()

    for num_tg in range(1, 33):
        print(f"\n[noc_hbm] === run_test num_tg={num_tg} ===", flush=True)
        bundle_dir = write_bundle(num_tg, root, overwrite=True)
        cmd = build_gem5_command(root, bundle_dir, gem5_binary, extra_args)
        log_path = log_dir / f"{num_tg:02d}tg.log"

        proc = subprocess.run(
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        text = proc.stdout + "\n" + proc.stderr
        log_path.write_text(text)

        aggregate_mb_s: float | str = ""
        if proc.returncode == 0:
            aggregate_mb_s = _sum_achieved_write_bw_mb_s(text)
            print(
                "[noc_hbm] num_tg={} aggregate_write_bw = {:.6f} MB/s "
                "({:.6f} GB/s)".format(
                    num_tg, aggregate_mb_s, aggregate_mb_s / 1000.0
                ),
                flush=True,
            )
        else:
            print(
                f"[noc_hbm] WARNING: gem5 exited {proc.returncode} for {num_tg}tg; "
                f"see {log_path}",
                file=sys.stderr,
                flush=True,
            )

        rows.append(
            {
                "num_tg": num_tg,
                "aggregate_write_bw_MBps": (
                    f"{aggregate_mb_s:.6f}"
                    if isinstance(aggregate_mb_s, float)
                    else ""
                ),
                "aggregate_write_bw_GBps": (
                    f"{aggregate_mb_s / 1000.0:.6f}"
                    if isinstance(aggregate_mb_s, float)
                    else ""
                ),
                "gem5_exit_code": proc.returncode,
                "log_path": os.fspath(log_path.relative_to(root)),
            }
        )

    with csv_path.open("w", newline="") as f:
        fieldnames = [
            "num_tg",
            "aggregate_write_bw_MBps",
            "aggregate_write_bw_GBps",
            "gem5_exit_code",
            "log_path",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[noc_hbm] Wrote CSV: {csv_path}")

    _plot_run_test_results(rows, graph_path)
    return 0 if all(row["gem5_exit_code"] == 0 for row in rows) else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate hbm_1stack_16GB/<N>tg topology bundle (conn/place/opts/nts/ncr) "
            "and optionally run noc_config.py."
        )
    )
    parser.add_argument(
        "--num-tg",
        type=int,
        default=NUM_TG,
        help="Number of traffic generators (1..32).",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="Only write/overwrite the bundle; do not launch gem5.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if the bundle directory already exists.",
    )
    parser.add_argument(
        "--gem5",
        default=GEM5_BINARY,
        help="Path to gem5 binary (repo-relative or absolute).",
    )
    parser.add_argument(
        "--run_test",
        action="store_true",
        help=(
            "Run 1tg through 32tg, sum printed Achieved Write BW lines, "
            "write CSV/logs, and plot aggregate GB/s."
        ),
    )
    parser.add_argument(
        "extra_gem5_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments passed to noc_config.py after '--'.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    extra = args.extra_gem5_args
    if extra and extra[0] == "--":
        extra = extra[1:]

    if args.run_test:
        return run_test_sweep(root, args.gem5, extra)

    num_tg = args.num_tg
    bundle_dir = write_bundle(
        num_tg,
        root,
        overwrite=not args.no_overwrite,
    )

    if args.no_run or not RUN_SIMULATION:
        print("[noc_hbm] Bundle ready (simulation skipped).")
        return 0

    cmd = build_gem5_command(root, bundle_dir, args.gem5, extra)
    return run_simulation(cmd, root)


if __name__ == "__main__":
    sys.exit(main())
