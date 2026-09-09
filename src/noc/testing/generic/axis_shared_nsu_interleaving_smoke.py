"""Exercise hardware-mode NSU interleaving with one fixed TID per NMU.

Run from Naviq with a rebuilt binary (works with gem5.fast):
  build/X86/gem5.fast --outdir=m5out/axis-shared-nsu-interleaving \
    src/noc/testing/generic/axis_shared_nsu_interleaving_smoke.py

The sink consumes raw AXIS beats. Only this test's Python checker reconstructs
frames, using the visible (TID, TDEST) pair. It checks exact packet bytes,
per-stream order, TLAST/TKEEP, actual interleaving, completion and outstanding
transactions. The optional NSU trace records FIFO enqueue, before the endpoint
handshake; successful Control completion additionally requires all sink TLASTs.
No RTL packet rebuilder is instantiated by this focused NoC regression.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys

import m5
from m5.objects import AxisPacketTrafficGenerator, AxisSinkNode, Root, sNocSlaveUnit


REPO = Path(__file__).resolve().parents[4]
for path in ("src/noc/testing/smartnic/common", "src/noc/setup/include"):
    sys.path.insert(0, str(REPO / path))
from smartnic_common import run_axis_test


out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--frame-sizes", default="1500,65,284,63")
parser.add_argument("--packets-per-source", type=int, default=8)
parser.add_argument("--sink-ready-percent", type=int, default=20)
parser.add_argument("--shared-vc", action="store_true")
args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]
sizes = [int(size) for size in args.frame_sizes.split(",")]
if not sizes or min(sizes) < 5 or max(sizes) > 65536:
    raise ValueError("Frame sizes must be 5..65536 bytes")
if args.packets_per_source < 1 or not 1 <= args.sink_ready_percent <= 100:
    raise ValueError("Positive packet counts and sink readiness 1..100 required")
if max(sizes) <= 64:
    raise ValueError("At least one multi-beat frame is required to show interleaving")

# Deliberately leave axis_reassemble_frames at its default. This test must fail
# if that default ever starts hiding hardware interleaving again.
sNocSlaveUnit.axis_tid_width = 6
sNocSlaveUnit.axis_beat_capture_file = str(out / "nsu_beats.jsonl")
connections = {
    "kind": "naviq.connections", "version": 1, "name": "axis_interleaving",
    "components": {
        name: {"node_type": node_type, "ports": {
            port: {"role": role, "protocol": "axis"}}}
        for name, node_type, port, role in (
            ("a", "AxisPacketTrafficGenerator", "m_axis", "master"),
            ("b", "AxisPacketTrafficGenerator", "m_axis", "master"),
            ("sink", "AxisSinkNode", "s_axis", "slave"))
    },
    "connections": [{"from": "a.m_axis", "to": "sink.s_axis"},
                    {"from": "b.m_axis", "to": "sink.s_axis"}],
}
placement = {
    "kind": "naviq.placement", "version": 1, "name": "axis_interleaving",
    "placements": {
        "a.m_axis": "NOC_NMU512_X3Y2",
        "b.m_axis": "NOC_NMU512_X3Y1",
        "sink.s_axis": "NOC_NSU512_X3Y10",
    },
}
for filename, value in (("connections.json", connections), ("placement.json", placement)):
    (out / filename).write_text(json.dumps(value, indent=2) + "\n")
with (out / "topology.log").open("w") as log:
    subprocess.run([
        "python3", str(REPO / "noc_testing/tools/topology/generate_ncr.py"),
        "--connections", str(out / "connections.json"),
        "--placement", str(out / "placement.json"),
        "--nts", str(out / "topology.nts"), "--ncr", str(out / "topology.ncr"),
        "--router", "shortest_path",
    ], cwd=REPO, stdout=log, stderr=subprocess.STDOUT, check=True)
if args.shared_vc:
    topology = json.loads((out / "topology.ncr").read_text())
    for path in topology["Paths"]:
        for net in path["Nets"]:
            net["VC"] = 1
    (out / "topology.ncr").write_text(json.dumps(topology, indent=2) + "\n")

expected = defaultdict(list)
for source_index, tid in enumerate((4, 5)):
    lines = []
    for sequence in range(args.packets_per_source):
        size = sizes[sequence % len(sizes)]
        tdest = 7 if sequence % 2 else 0
        frame = (bytes([0xA0 + source_index * 16]) + sequence.to_bytes(4, "big")
                 + bytes((i + 64 * source_index + sequence) % 256
                         for i in range(size - 5)))
        expected[(tid, tdest)].append(frame.hex())
        lines.append(f"{tdest} {frame.hex()}\n")
    (out / f"source{source_index}.txt").write_text("".join(lines))

sources = []


def make_nsu(tile, options):
    if tile != "M00_AXIS_nsu":
        raise ValueError(f"Unexpected NSU {tile}")
    return AxisSinkNode(
        data_width=512, id_width=6, dest_width=10,
        expected_packets=2 * args.packets_per_source,
        ready_percent=args.sink_ready_percent)


def make_nmu(tile, options):
    if tile not in ("S00_AXIS_nmu", "S01_AXIS_nmu"):
        raise ValueError(f"Unexpected NMU {tile}")
    index = 0 if tile == "S00_AXIS_nmu" else 1
    source = AxisPacketTrafficGenerator(
        data_width=512, tid_width=6, tdest_width=10, tid=4 + index,
        packet_file=str(out / f"source{index}.txt"),
        max_packets=args.packets_per_source, min_gap_cycles=0, max_gap_cycles=0)
    sources.append(source)
    return source


exit_causes = []
original_simulate = m5.simulate


def record_simulate(*simulate_args, **simulate_kwargs):
    event = original_simulate(*simulate_args, **simulate_kwargs)
    exit_causes.append(event.getCause())
    return event


m5.simulate = record_simulate
sys.argv += ["--sys-clock", "400MHz", "--noc-clock", "1GHz",
             "--sim-cycles", "5000000000", "--abs-max-tick", "5000000000"]
run_axis_test(str(out / "topology"), make_nsu, make_nmu,
              axis_tdest_aliases=[(source, 7, "M00_AXIS_nsu")
                                 for source in ("S00_AXIS_nmu", "S01_AXIS_nmu")])

errors = []
partial = defaultdict(bytearray)
received = defaultdict(list)
beats = [json.loads(line) for line in (out / "nsu_beats.jsonl").read_text().splitlines()]
interleaved_beats = 0
previous = None
for index, beat in enumerate(beats):
    # These are the only identities available to receiving RTL. Do not key
    # reconstruction by source_nmu, NoC packet IDs or simulator debug metadata.
    key = (beat["tid"], beat["tdest"])
    data = bytes.fromhex(beat["hex"])
    if key not in expected:
        errors.append(f"beat {index}: unexpected visible stream {key}")
    if beat["beat_index"] != index or beat["event"] != "endpoint_fifo_enqueue":
        errors.append(f"beat {index}: malformed enqueue trace")
    if not 1 <= len(data) <= 64 or beat["bytes"] != len(data):
        errors.append(f"beat {index}: invalid byte count")
    if beat["tkeep"] != (1 << len(data)) - 1:
        errors.append(f"beat {index}: invalid packed TKEEP")
    if not beat["tlast"] and len(data) != 64:
        errors.append(f"beat {index}: non-final chunk is not 64 bytes")
    if previous is not None and previous != key and partial[previous]:
        interleaved_beats += 1
    partial[key].extend(data)
    if beat["tlast"]:
        received[key].append(partial.pop(key).hex())
    previous = key

if dict(received) != dict(expected):
    errors.append("Reconstructed packet bytes, counts or per-stream order differ")
if any(partial.values()):
    errors.append("Partial packets remain after simulation")
if interleaved_beats == 0:
    errors.append("No packet interleaving observed; this did not exercise hardware mode")
emitted = [source.emittedPackets() for source in sources]
if not all(source.finished() for source in sources) or emitted != [args.packets_per_source] * 2:
    errors.append("Sources did not finish the configured packet count")
network_pending = Root.getInstance().system.noc.network.hasOutstandingTransactions()
if network_pending:
    errors.append("Outstanding NoC transactions remain")
if not exit_causes or exit_causes[-1] != "Reads and writes completed":
    errors.append("Simulation did not report endpoint completion")
if m5.curTick() >= 5000000000:
    errors.append("Simulation reached the timeout instead of endpoint completion")

result = {
    "pass": not errors, "errors": errors, "tids": [4, 5],
    "axis_reassemble_frames": False, "shared_vc": args.shared_vc,
    "sink_ready_percent": args.sink_ready_percent,
    "emitted_packets": emitted, "received_packets": sum(map(len, received.values())),
    "beat_count": len(beats), "interleaved_beats": interleaved_beats,
    "network_pending": network_pending, "exit_causes": exit_causes,
    "expected": {f"{tid}:{tdest}": frames for (tid, tdest), frames in expected.items()},
    "received": {f"{tid}:{tdest}": frames for (tid, tdest), frames in received.items()},
}
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("AXIS_SHARED_NSU_INTERLEAVING_RESULT", json.dumps(
    {key: value for key, value in result.items() if key not in ("expected", "received")}))
sys.exit(0 if not errors else 1)
