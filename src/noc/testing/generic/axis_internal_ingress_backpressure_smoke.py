"""Fill the NCRB/NIDB shared ingress storage, then release real AXIS sinks.

Run from Naviq with ordinary Python so assertions inspect fully flushed traces:
  python3 src/noc/testing/generic/axis_internal_ingress_backpressure_smoke.py \
    --gem5 build/X86/gem5.fast --outdir m5out/internal_ingress_backpressure

Both cases send VCs 1 and 5 across the same physical link in each direction
simultaneously. The NCRB's two directions use separate NCRB instances; the NIDB
case exercises both incoming ports of each of two connected NIDBs. Real sinks
hold TREADY low until a fixed tick, long enough for backpressure to stop every
source, then become fully ready. Every payload, count and per-stream order is
checked after recovery. Sparse per-VC trace rows are summed per router/input;
the sum must reach exactly eight and never exceed eight. The ordinary same-VC
passthrough regression runs as a third case to preserve convergent arbitration.

No PE RTL, pre-existing output files, or external traffic fixtures are needed.
"""

import argparse
from collections import defaultdict, deque
import configparser
import csv
import json
import os
from pathlib import Path
import subprocess
import sys


REPO = Path(__file__).resolve().parents[4]
CAPACITY = 8
VCS = (1, 5)
SIZES = (1024, 140, 176, 1088)
SPINES = {
    "ncrb": (
        ("NOC_NPS7575_X0Y1", "NOC_NPP_RPTR_X0Y3", "NOC_NCRB_SSIT_X1Y1",
         "NOC_NPP_RPTR_X1Y0", "NOC_NPS7575_X5Y0"),
        ("NOC_NPS7575_X5Y0", "NOC_NPP_RPTR_X1Y0", "NOC_NCRB_SSIT_X1Y0",
         "NOC_NPP_RPTR_X0Y3", "NOC_NPS7575_X0Y1")),
    "nidb": (
        ("NOC_NPS7575_X5Y0", "NOC_NIDB_X1Y1", "NOC_NIDB_X1Y3",
         "NOC_NPS7575_X5Y2"),
        ("NOC_NPS7575_X5Y2", "NOC_NIDB_X1Y3", "NOC_NIDB_X1Y1",
         "NOC_NPS7575_X5Y0")),
}
ENDPOINT_COORDS = {
    "ncrb": (("X0Y3", "X0Y4"), ("X1Y3", "X1Y4")),
    "nidb": (("X1Y3", "X1Y4"), ("X1Y8", "X1Y9")),
}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def make_routes(case):
    """Pin the tested crossing; ordinary shortest paths attach its endpoints."""
    physical = json.loads((REPO / "noc_testing/tools/topology/connections_list.json")
                          .read_text())["Connections"]
    outgoing = defaultdict(list)
    for edge in physical:
        outgoing[edge["Source"]].append(edge)

    def attach(source, destination):
        work = deque([(source, [])])
        seen = {source}
        while work:
            node, edges = work.popleft()
            if node == destination:
                return edges
            for edge in outgoing[node]:
                target = edge["Target"]
                if target in seen:
                    continue
                # Attachments cannot accidentally cross another NCRB/NIDB or
                # use another endpoint as an intermediate forwarding node.
                if target != destination and not any(
                        kind in target for kind in ("NPS", "RPTR")):
                    continue
                seen.add(target)
                work.append((target, edges + [edge]))
        raise ValueError(f"No local attachment from {source} to {destination}")

    routes = []
    for direction, spine in enumerate(SPINES[case]):
        middle = []
        for source, destination in zip(spine, spine[1:]):
            matching = [edge for edge in outgoing[source] if edge["Target"] == destination]
            if len(matching) != 1:
                raise ValueError(f"Test crossing changed: {source} -> {destination}")
            middle.extend(matching)
        for lane, vc in enumerate(VCS):
            source = "NOC_NMU512_" + ENDPOINT_COORDS[case][direction][lane]
            sink = "NOC_NSU512_" + ENDPOINT_COORDS[case][1 - direction][lane]
            edges = attach(source, spine[0]) + middle + attach(spine[-1], sink)
            nodes = [edge["Source"] for edge in edges] + [sink]
            if len(nodes) != len(set(nodes)):
                raise ValueError(f"Test route contains a loop: {nodes}")
            routes.append({"vc": vc, "direction": direction, "edges": [
                [edge[key] for key in ("Source", "SourcePort", "Target", "TargetPort")]
                for edge in edges]})
    return routes


def make_topology(out, case):
    routes = make_routes(case)
    connections = {"kind": "naviq.connections", "version": 1,
                   "name": "internal_ingress_backpressure", "components": {}, "connections": []}
    placements = {}
    targets = defaultdict(set)
    for index, route in enumerate(routes):
        for component, kind, port, role, physical in (
                (f"source{index}", "AxisPacketTrafficGenerator", "m_axis", "master", route["edges"][0][0]),
                (f"sink{index}", "AxisSinkNode", "s_axis", "slave", route["edges"][-1][2])):
            connections["components"][component] = {
                "node_type": kind, "ports": {port: {"role": role, "protocol": "axis"}}}
            placements[f"{component}.{port}"] = physical
        connections["connections"].append({"from": f"source{index}.m_axis", "to": f"sink{index}.s_axis"})
        for _, _, target, inport in route["edges"]:
            if "NCRB" in target or "NIDB" in target:
                targets[target].add(inport)
    write_json(out / "connections.json", connections)
    write_json(out / "placement.json", {
        "kind": "naviq.placement", "version": 1, "placements": placements})
    with (out / "topology.log").open("w") as log:
        subprocess.run([
            "python3", str(REPO / "noc_testing/tools/topology/generate_ncr.py"),
            "--connections", str(out / "connections.json"),
            "--placement", str(out / "placement.json"),
            "--nts", str(out / "stress.nts"), "--ncr", str(out / "stress.ncr"),
            "--router", "shortest_path"], cwd=REPO,
            stdout=log, stderr=subprocess.STDOUT, check=True)
    topology = json.loads((out / "stress.ncr").read_text())
    for index, route in enumerate(routes):
        path = next(path for path in topology["Paths"]
                    if path["From"].endswith(f"/S{index:02d}_AXIS_nmu"))
        if not path["To"].endswith(f"/M{index:02d}_AXIS_nsu") or len(path["Nets"]) != 1:
            raise ValueError("Unexpected source/destination topology mapping")
        net = path["Nets"][0]
        if net["CommType"] != "WRITE":
            raise ValueError("Expected AXIS WRITE net")
        net["VC"] = route["vc"]
        net["Connections"] = [item for edge in route["edges"] for item in edge]
    write_json(out / "stress.ncr", topology)
    return routes, {name: sorted(ports) for name, ports in targets.items()}


def simulate():
    import m5
    from m5.objects import AxisPacketTrafficGenerator, AxisSinkNode, Root

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--case", choices=SPINES, required=True)
    parser.add_argument("--packets", type=int, default=256)
    parser.add_argument("--hold-tick", type=int, default=8000000)
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]
    out = Path(m5.options.outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ["NOC_CSV_OUTPUT_DIR"] = str(out / "csv")
    for relative in ("src/noc/testing/smartnic/common", "src/noc/setup/include"):
        sys.path.insert(0, str(REPO / relative))
    from smartnic_common import run_axis_test

    routes, targets = make_topology(out, args.case)
    expected = defaultdict(list)
    for index in range(4):
        lines = []
        for sequence in range(args.packets):
            size = SIZES[sequence % len(SIZES)]
            packet = bytes((offset + 37 * index + sequence) % 256 for offset in range(size - 12))
            packet += index.to_bytes(4, "big") + sequence.to_bytes(4, "big") + size.to_bytes(4, "big")
            expected[(26 + index, 10 + index)].append(packet.hex())
            lines.append(f"{10 + index} {packet.hex()}\n")
        (out / f"source{index}.txt").write_text("".join(lines))
    sources = {}

    def make_nmu(name, options):
        index = int(name[1:3])
        source = AxisPacketTrafficGenerator(
            data_width=512, tid_width=6, tdest_width=10, tid=26 + index,
            packet_file=str(out / f"source{index}.txt"), max_packets=args.packets,
            min_gap_cycles=0, max_gap_cycles=0, endpoint_index=index)
        sources[index] = source
        return source

    def make_nsu(name, options):
        return AxisSinkNode(data_width=512, id_width=6, dest_width=10,
                            ready_percent=100, ready_hold_until=args.hold_tick,
                            expected_packets=args.packets)

    original_instantiate = m5.instantiate

    def capture_instantiate(*pos, **kw):
        network = Root.getInstance().system.noc.network
        for index in range(4):
            if bool(network.netifs[index].axis_reassemble_frames):
                raise ValueError("Regression requires hardware NSU beat delivery")
            network.netifs[index].axis_tid_width = 6
            network.netifs[index].axis_beat_capture_file = str(out / f"nsu{index}.jsonl")
        network.nps_queue_trace_mode = 1
        network.nps_queue_trace_path = str(out / "nps_queue_trace.csv")
        return original_instantiate(*pos, **kw)

    m5.instantiate = capture_instantiate
    original_simulate = m5.simulate
    checkpoints = []
    causes = []

    def capture_simulate(*pos, **kw):
        for tick in (args.hold_tick // 2, args.hold_tick * 3 // 4):
            event = original_simulate(tick - m5.curTick())
            causes.append(event.getCause())
            checkpoints.append({"tick": m5.curTick(), "sources": [
                json.loads(sources[index].trafficMetrics()) for index in range(4)]})
        event = original_simulate(500000000 - m5.curTick())
        causes.append(event.getCause())
        return event

    m5.simulate = capture_simulate
    sys.argv += ["--sys-clock", "400MHz", "--noc-clock", "1GHz",
                 "--sim-cycles", "500000000", "--abs-max-tick", "500000000"]
    run_axis_test(str(out / "stress"), make_nsu, make_nmu, axis_tdest_aliases=[
        (f"S{i:02d}_AXIS_nmu", 10 + i, f"M{i:02d}_AXIS_nsu") for i in range(4)])

    errors = []
    received = defaultdict(list)
    for index in range(4):
        partial = bytearray()
        for beat_index, line in enumerate((out / f"nsu{index}.jsonl").read_text().splitlines()):
            beat = json.loads(line)
            data = bytes.fromhex(beat["hex"])
            key = (beat["tid"], beat["tdest"])
            if (key != (26 + index, 10 + index) or beat["beat_index"] != beat_index
                    or beat["event"] != "endpoint_fifo_enqueue"):
                errors.append(f"NSU {index}: unexpected identity/enqueue trace")
            if (not 1 <= len(data) <= 64 or beat["bytes"] != len(data)
                    or beat["tkeep"] != (1 << len(data)) - 1
                    or (not beat["tlast"] and len(data) != 64)):
                errors.append(f"NSU {index}: invalid byte count/TKEEP/chop")
            partial.extend(data)
            if beat["tlast"]:
                received[key].append(partial.hex())
                partial.clear()
        if partial:
            errors.append(f"NSU {index}: partial packet remains")
    if dict(received) != dict(expected):
        errors.append("Packet bytes, counts or per-stream order differ")
    for index, (before, after) in enumerate(zip(
            checkpoints[0]["sources"], checkpoints[1]["sources"])):
        if not 0 < before["packets_accepted"] < args.packets:
            errors.append(f"Source {index}: hold did not stop an active incomplete source")
        if any(before[key] != after[key] for key in ("beats_accepted", "bytes_accepted")):
            errors.append(f"Source {index}: continued accepting beats during settled sink hold")
        if after["backpressure_cycles"] <= before["backpressure_cycles"]:
            errors.append(f"Source {index}: no upstream backpressure during sink hold")
    emitted = [sources[index].emittedPackets() for index in range(4)]
    if emitted != [args.packets] * 4 or not all(source.finished() for source in sources.values()):
        errors.append("Sources did not recover and complete")
    pending = Root.getInstance().system.noc.network.hasOutstandingTransactions()
    if pending:
        errors.append("Outstanding NoC transactions remain")
    if causes[-1] != "Reads and writes completed" or m5.curTick() <= args.hold_tick:
        errors.append("Simulation did not complete after sink release")
    m5.stats.dump()
    result = {"pass": not errors, "errors": errors, "parameters": vars(args),
              "routes": routes, "target_inputs": targets, "checkpoints": checkpoints,
              "emitted": emitted, "received": {f"{tid}:{dest}": len(packets)
                  for (tid, dest), packets in received.items()},
              "network_pending": pending, "tick": m5.curTick(), "exit_causes": causes}
    write_json(out / "result.json", result)
    print("AXIS_INTERNAL_INGRESS_BACKPRESSURE", json.dumps(result))
    sys.exit(0 if not errors else 1)


def check_trace(out, result):
    errors = []
    targets = result["target_inputs"]
    hold = result["parameters"]["hold_tick"]
    peaks = defaultdict(int)
    mixed = set()
    full_samples = defaultdict(int)
    mixed_full_samples = defaultdict(int)
    simultaneous_full_samples = 0
    last_internal_tick = 0
    sample = defaultdict(dict)
    sample_tick = None

    def finish_sample(tick):
        nonlocal simultaneous_full_samples, last_internal_tick
        full = 0
        for key, vcs in sample.items():
            depth = sum(vcs.values())
            peaks[key] = max(peaks[key], depth)
            last_internal_tick = max(last_internal_tick, tick)
            if depth > CAPACITY:
                raise AssertionError(f"Internal storage overflow: tick={tick}, link={key}, VCs={vcs}")
            if len(vcs) >= 2:
                mixed.add(key)
            if hold // 2 <= tick < hold * 3 // 4 and depth == CAPACITY:
                full_samples[key] += 1
                if len(vcs) >= 2:
                    mixed_full_samples[key] += 1
                full += 1
        if full == sum(len(ports) for ports in targets.values()):
            simultaneous_full_samples += 1

    with (out / "nps_queue_trace.csv").open(newline="") as trace:
        for row in csv.DictReader(trace):
            if row["queue_kind"] != "internal_ingress":
                continue
            tick = int(row["tick"])
            if sample_tick is not None and tick != sample_tick:
                finish_sample(sample_tick)
                sample.clear()
            sample_tick = tick
            key = (row["nocname"], int(row["inport"]))
            vc, depth = int(row["vc"]), int(row["depth"])
            if vc < 0 or depth <= 0 or vc in sample[key]:
                raise AssertionError(f"Malformed/duplicate internal ingress trace row: {row}")
            sample[key][vc] = depth
    if sample_tick is not None:
        finish_sample(sample_tick)
    for router, ports in targets.items():
        keys = [key for key in peaks if key[0] == router]
        if len(keys) != len(ports):
            errors.append(f"{router}: expected {len(ports)} active internal inputs, observed {keys}")
        for key in keys:
            if peaks[key] != CAPACITY or full_samples[key] < 10:
                errors.append(f"{key}: did not sustain exactly eight flits during sink hold")
            if mixed_full_samples[key] < 10:
                errors.append(f"{key}: did not sustain multiple VCs sharing the full eight-slot pool")
    if simultaneous_full_samples < 10:
        errors.append("Both directions did not independently sustain full internal queues together")
    if last_internal_tick <= hold:
        errors.append("No internal ingress activity after sink release")
    evidence = {"capacity": CAPACITY, "links": [
        {"router": name, "inport": inport, "peak": peaks[(name, inport)],
         "mixed_vcs": (name, inport) in mixed,
         "mixed_full_blocked_samples": mixed_full_samples[(name, inport)],
         "full_blocked_samples": full_samples[(name, inport)]}
        for name, inport in sorted(peaks)],
        "simultaneous_full_samples": simultaneous_full_samples,
        "last_internal_tick": last_internal_tick}
    return errors, evidence


def check_stats(out, result):
    config = configparser.ConfigParser(interpolation=None)
    config.read(out / "config.ini")
    router_paths = {config[section]["nocname"]: section for section in config.sections()
                    if config[section].get("type") == "NocGarnetRouter"}
    stats = {}
    for line in (out / "stats.txt").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 2 and ".internal_ingress_" in fields[0]:
            stats[fields[0]] = float(fields[1])
    errors = []
    evidence = []
    # AXIS chops are at most 64 bytes, with four 16-byte flits per full chop.
    # Two sources traverse each tested incoming link, each exactly once.
    flits = 2 * sum((SIZES[sequence % len(SIZES)] + 15) // 16
                    for sequence in range(result["parameters"]["packets"]))
    for link in result["trace"]["links"]:
        name, inport = link["router"], link["inport"]
        values = {}
        for metric in ("accepted", "drained", "blocked_cycles", "peak", "average"):
            base = f"{router_paths[name]}.internal_ingress_{metric}"
            # gem5 omits the ::0 suffix for vectors with just one element.
            key = base if inport == 0 and base in stats else f"{base}::{inport}"
            if key not in stats:
                errors.append(f"Missing ingress statistic: {key}")
            values[metric] = stats.get(key, 0)
        if values["accepted"] != flits or values["drained"] != flits:
            errors.append(f"{name} input {inport}: admitted/drained counts differ from {flits} expected flits")
        if values["peak"] != CAPACITY or not 0 < values["average"] <= CAPACITY:
            errors.append(f"{name} input {inport}: invalid peak/average internal occupancy")
        if values["blocked_cycles"] <= 0:
            errors.append(f"{name} input {inport}: no admission stalls at full capacity")
        evidence.append({"router": name, "inport": inport, "expected_flits": flits, **values})
    return errors, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gem5", type=Path, default=REPO / "build/X86/gem5.fast")
    parser.add_argument("--outdir", type=Path, default=REPO / "m5out/internal_ingress_backpressure")
    parser.add_argument("--case", choices=("all", *SPINES), default="all")
    parser.add_argument("--packets", type=int, default=256)
    parser.add_argument("--hold-tick", type=int, default=8000000)
    parser.add_argument("--skip-same-vc", action="store_true")
    args = parser.parse_args()
    if args.packets < 64 or args.hold_tick < 1000000:
        parser.error("Use at least 64 packets and a sink hold of at least 1,000,000 ticks")
    gem5 = args.gem5.resolve()
    base = args.outdir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    summary = {"pass": True, "cases": {}}
    for case in (tuple(SPINES) if args.case == "all" else (args.case,)):
        out = base / case
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").unlink(missing_ok=True)
        with (out / "simulation.log").open("w") as log:
            completed = subprocess.run([
                str(gem5), f"--outdir={out}", str(Path(__file__).resolve()),
                "--case", case, "--packets", str(args.packets),
                "--hold-tick", str(args.hold_tick)], cwd=REPO,
                stdout=log, stderr=subprocess.STDOUT)
        if not (out / "result.json").exists():
            case_result = {"pass": False, "errors": [f"Simulation failed; see {out / 'simulation.log'}"]}
        else:
            case_result = json.loads((out / "result.json").read_text())
            trace_errors, evidence = check_trace(out, case_result)
            case_result["errors"].extend(trace_errors)
            case_result["trace"] = evidence
            stat_errors, stat_evidence = check_stats(out, case_result)
            case_result["errors"].extend(stat_errors)
            case_result["stats"] = stat_evidence
            case_result["pass"] = not case_result["errors"] and completed.returncode == 0
            write_json(out / "result.json", case_result)
        summary["cases"][case] = case_result
        summary["pass"] &= case_result["pass"]
        print(f"{case}: {'PASS' if case_result['pass'] else 'FAIL'} ({out / 'result.json'})", flush=True)
    if not args.skip_same_vc:
        out = base / "same_vc"
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").unlink(missing_ok=True)
        with (out / "simulation.log").open("w") as log:
            completed = subprocess.run([
                str(gem5), f"--outdir={out}", str(Path(__file__).with_name("axis_same_vc_passthrough_smoke.py")),
                "--packets-per-source", str(args.packets), "--sink-ready-percent", "17"],
                cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, "NOC_CSV_OUTPUT_DIR": str(out / "csv")})
        case_result = (json.loads((out / "result.json").read_text()) if (out / "result.json").exists()
                       else {"pass": False, "errors": [f"Simulation failed; see {out / 'simulation.log'}"]})
        case_result["pass"] &= completed.returncode == 0
        summary["cases"]["same_vc"] = case_result
        summary["pass"] &= case_result["pass"]
        print(f"same_vc: {'PASS' if case_result['pass'] else 'FAIL'} ({out / 'result.json'})", flush=True)
    write_json(base / "result.json", summary)
    return 0 if summary["pass"] else 1


if __name__ == "__m5_main__":
    simulate()
elif __name__ == "__main__":
    sys.exit(main())
