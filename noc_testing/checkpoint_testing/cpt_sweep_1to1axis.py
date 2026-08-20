#!/usr/bin/env python3
"""
Sweep AxisRandomTrafficGenerator seeds and mid-run checkpoint ticks for 1_to_1axis
topology, then restore and run to completion. Reports failures and causes.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GEM5 = REPO / "build" / "NULL" / "gem5.debug"
NOC_CONFIG = REPO / "src" / "noc" / "main" / "noc_config.py"
TOPO_BASE = REPO / "src" / "noc" / "topology" / "topologies" / "1_to_1axis"

# ~10 distinct seeds; include original 736 from the default JSON
SEEDS = (101, 202, 303, 736, 1001, 2048, 5000, 8888, 12345, 99999)

MAX_CP_TICK = 6_755_000
MIN_CP_TICK = 200_000
TICKS_PER_SEED = 10
# Schedule of checkpoint ticks: reproducible, spread across [MIN, MAX]
SCHED_RNG_SEED = 20260426

# Upper bound for post-restore and single-shot sims; natural exit often occurs earlier
ABS_MAX_TICK = 50_000_000


def _round_up_multiple(x: int, m: int) -> int:
    if m <= 0:
        raise ValueError("multiple must be > 0")
    return ((x + m - 1) // m) * m


def _round_down_multiple(x: int, m: int) -> int:
    if m <= 0:
        raise ValueError("multiple must be > 0")
    return (x // m) * m


def build_base_node_config() -> dict:
    with open(f"{TOPO_BASE}_node_config.json", encoding="utf-8") as f:
        return json.load(f)


def materialize_workdir(seed: int) -> Path:
    """Per-seed work dir: copy .nts/.ncr; write _node_config.json with chosen seed."""
    wdir = OUT_ROOT / f"seed_{seed}"
    wdir.mkdir(parents=True, exist_ok=True)
    for ext in (".nts", ".ncr"):
        shutil.copy2(TOPO_BASE.with_suffix(ext), wdir / f"1_to_1axis{ext}")
    data = build_base_node_config()
    for node in data.get("nodes", []):
        if node.get("node_type") == "AxisRandomTrafficGenerator":
            node.setdefault("parameters", {})["seed"] = int(seed)
            break
    else:
        print(f"FATAL: no AxisRandomTrafficGenerator in template", file=sys.stderr)
        sys.exit(2)
    with open(wdir / "1_to_1axis_node_config.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return wdir


def run_gem5(
    workdir: Path,
    *,
    env: dict,
    log_path: Path,
) -> tuple[int, str]:
    workdir = workdir.resolve()
    topo = workdir / "1_to_1axis"
    cmd = [
        str(GEM5),
        str(NOC_CONFIG),
        f"--noc-topology={topo}",
        f"--abs-max-tick={ABS_MAX_TICK}",
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        p = subprocess.run(
            cmd,
            cwd=REPO,
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return p.returncode, text


def pick_ticks(r: random.Random, n: int, lo: int, hi: int, *, quantum: int = 1000) -> list[int]:
    """
    Pick n unique checkpoint ticks, constrained to multiples of `quantum`.
    For this repo, `quantum=1000` corresponds to full NoC cycles (1ps ticks, 1ns cycle).
    """
    lo_q = _round_up_multiple(lo, quantum)
    hi_q = _round_down_multiple(hi, quantum)
    if lo_q > hi_q:
        raise ValueError(
            f"No valid ticks divisible by {quantum} in range [{lo}, {hi}] "
            f"(rounded to [{lo_q}, {hi_q}])."
        )

    lo_i = lo_q // quantum
    hi_i = hi_q // quantum
    s: set[int] = set()
    while len(s) < n:
        s.add(r.randint(lo_i, hi_i))
    return sorted(v * quantum for v in s)


def classify_failure(text: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "Can't unserialize" in line or "FATAL" in line or "fatal" in line.lower():
            # grab a few lines of context
            start = max(0, i - 2)
            end = min(len(lines), i + 4)
            return "\n".join(lines[start:end])
    if "panic" in text.lower() or "assert" in text.lower():
        for i, line in enumerate(lines):
            if "assert" in line.lower() or "panic" in line.lower():
                start = max(0, i - 1)
                end = min(len(lines), i + 5)
                return "\n".join(lines[start:end])
    return "unknown; see log"


OUT_ROOT = REPO / "m5out" / "cpt_sweep_1to1axis"


def main() -> int:
    if not GEM5.is_file():
        print(f"Missing binary: {GEM5}", file=sys.stderr)
        return 1
    if not NOC_CONFIG.is_file():
        print(f"Missing config: {NOC_CONFIG}", file=sys.stderr)
        return 1

    import argparse

    p = argparse.ArgumentParser()
    p.add_argument(
        "--only-seed",
        type=int,
        default=None,
        help="If set, only this seed (for smoke tests).",
    )
    p.add_argument(
        "--ticks-per-seed",
        type=int,
        default=TICKS_PER_SEED,
        help=f"default {TICKS_PER_SEED}",
    )
    p.add_argument(
        "--min-cp-tick",
        type=int,
        default=MIN_CP_TICK,
        help="Lower bound for random checkpoint ticks (inclusive).",
    )
    p.add_argument(
        "--max-cp-tick",
        type=int,
        default=MAX_CP_TICK,
        help="Upper bound for random checkpoint ticks (inclusive).",
    )
    args = p.parse_args()
    ticks_n = max(1, args.ticks_per_seed)
    min_cp, max_cp = args.min_cp_tick, args.max_cp_tick
    if min_cp > max_cp:
        print("min-cp-tick must be <= max-cp-tick", file=sys.stderr)
        return 1

    seeds = [args.only_seed] if args.only_seed is not None else list(SEEDS)
    report: list[dict] = []
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    base_env = os.environ.copy()
    # Avoid picking up a stray CHECKPOINT/RESTORE from the shell
    for k in (
        "CHECKPOINT_AT_TICKS",
        "CHECKPOINT_DIR",
        "RESTORE_DIR",
    ):
        base_env.pop(k, None)

    for seed in seeds:
        r = random.Random(SCHED_RNG_SEED + int(seed) * 1009)
        ticks = pick_ticks(r, ticks_n, min_cp, max_cp)
        wdir = materialize_workdir(seed)

        for tick in ticks:
            tag = f"seed{seed}_tick{tick}"
            cpt_dir = (OUT_ROOT / f"seed_{seed}" / f"cpt_{tick}").resolve()
            if cpt_dir.exists():
                shutil.rmtree(cpt_dir)
            cpt_dir.mkdir(parents=True, exist_ok=True)
            cpt_log = OUT_ROOT / f"seed_{seed}" / f"checkpoint_{tick}.log"
            e1 = base_env.copy()
            e1["CHECKPOINT_AT_TICKS"] = str(tick)
            e1["CHECKPOINT_DIR"] = str(cpt_dir)
            e1.pop("RESTORE_DIR", None)
            code1, out1 = run_gem5(wdir, env=e1, log_path=cpt_log)

            e2 = base_env.copy()
            e2["RESTORE_DIR"] = str(cpt_dir)
            e2.pop("CHECKPOINT_AT_TICKS", None)
            e2.pop("CHECKPOINT_DIR", None)
            res_log = OUT_ROOT / f"seed_{seed}" / f"restore_{tick}.log"
            code2, out2 = run_gem5(wdir, env=e2, log_path=res_log)

            rec = {
                "seed": seed,
                "tick": tick,
                "checkpoint_code": code1,
                "restore_code": code2,
            }
            fail_cause: str | None = None
            if code1 != 0:
                rec["failed_phase"] = "checkpoint"
                fail_cause = classify_failure(out1)
            elif code2 != 0:
                rec["failed_phase"] = "restore"
                fail_cause = classify_failure(out2)
            if fail_cause is not None:
                rec["cause_snippet"] = fail_cause
            report.append(rec)
            st = (
                "OK"
                if "failed_phase" not in rec
                else f"FAIL {rec['failed_phase']}"
            )
            snippet = (fail_cause or "")[:200] + ("..." if len(fail_cause or "") > 200 else "")
            print(f"{tag}: {st}" + (f" — {snippet}" if snippet else ""))

    summary = OUT_ROOT / "sweep_report.json"
    with open(summary, "w", encoding="utf-8") as f:
        json.dump(
            {
                "seeds": list(seeds),
                "min_cp": min_cp,
                "max_cp": max_cp,
                "abs_max_tick": ABS_MAX_TICK,
                "ticks_per_seed": ticks_n,
                "results": report,
            },
            f,
            indent=2,
        )
        f.write("\n")
    fails = [r for r in report if "failed_phase" in r]
    print(f"\nWrote {summary}")
    print(f"Total cases: {len(report)}, failures: {len(fails)}")
    for r in fails:
        print("---")
        print(json.dumps(r, indent=2)[:2000])
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
