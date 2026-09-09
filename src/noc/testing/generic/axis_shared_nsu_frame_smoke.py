"""Check the explicit synthetic NSU frame-reassembly compatibility option.

Run from Naviq:
  build/X86/gem5.opt --outdir=m5out/axis-shared-nsu \
    src/noc/testing/generic/axis_shared_nsu_frame_smoke.py

This intentionally opts into non-hardware whole-frame reconstruction inside
the NSU; it does not establish correctness of a PE's RTL packet rebuilder.
For hardware interleaving use axis_shared_nsu_interleaving_smoke.py instead.
Each source sends one 284-byte frame, crossing the 64-byte NoC packet
boundary. The placements match the checksum NMUs and dummy loopback NSU.
The test saves result.json and exits nonzero on corrupt or missing frames.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

import m5
from m5.objects import AxisPacketCheckerSink, AxisPacketTrafficGenerator, Root, sNocSlaveUnit


REPO = Path(__file__).resolve().parents[4]
for path in ("src/noc/testing/smartnic/common", "src/noc/setup/include"):
    sys.path.insert(0, str(REPO / path))
from smartnic_common import run_axis_test


out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--frame-sizes", default="284")
parser.add_argument("--packets-per-source", type=int, default=1)
parser.add_argument("--sink-ready-percent", type=int, default=100)
parser.add_argument("--different-tids", action="store_true")
parser.add_argument("--tdest-aliases", action="store_true")
parser.add_argument("--shared-vc", action="store_true")
parser.add_argument("--complete-frame-slots", type=int, default=8)
test_args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]
sizes = [int(value) for value in test_args.frame_sizes.split(",")]
if min(sizes) < 5 or test_args.packets_per_source < 1:
    raise ValueError("Positive packet counts and frame sizes >= 5 are required")
if not 1 <= test_args.sink_ready_percent <= 100:
    raise ValueError("Sink readiness must be 1..100 percent")
sNocSlaveUnit.axis_complete_frames = test_args.complete_frame_slots
sNocSlaveUnit.axis_reassemble_frames = True
sNocSlaveUnit.axis_tid_width = 6
connections = {
    "kind": "naviq.connections", "version": 1, "name": "axis_shared_nsu",
    "components": {
        "a": {"node_type": "AxisPacketTrafficGenerator", "ports": {
            "m_axis": {"role": "master", "protocol": "axis"}}},
        "b": {"node_type": "AxisPacketTrafficGenerator", "ports": {
            "m_axis": {"role": "master", "protocol": "axis"}}},
        "sink": {"node_type": "AxisPacketCheckerSink", "ports": {
            "s_axis": {"role": "slave", "protocol": "axis"}}},
    },
    "connections": [{"from": "a.m_axis", "to": "sink.s_axis"},
                    {"from": "b.m_axis", "to": "sink.s_axis"}],
}
placement = {
    "kind": "naviq.placement", "version": 1, "name": "axis_shared_nsu",
    "placements": {
        "a.m_axis": "NOC_NMU512_X3Y2",
        "b.m_axis": "NOC_NMU512_X3Y1",
        "sink.s_axis": "NOC_NSU512_X3Y10",
    },
}
for filename, content in (("connections.json", connections), ("placement.json", placement)):
    (out / filename).write_text(json.dumps(content, indent=2) + "\n")
with (out / "topology.log").open("w") as log:
    subprocess.run([
        "python3", str(REPO / "noc_testing/tools/topology/generate_ncr.py"),
        "--connections", str(out / "connections.json"),
        "--placement", str(out / "placement.json"),
        "--nts", str(out / "topology.nts"), "--ncr", str(out / "topology.ncr"),
        "--router", "shortest_path",
    ], cwd=REPO, stdout=log, stderr=subprocess.STDOUT, check=True)
if test_args.shared_vc:
    # Force both source paths onto the same physical VC so a capacity-stalled
    # final flit can have the other source's continuation queued behind it.
    ncr = json.loads((out / "topology.ncr").read_text())
    for path in ncr["Paths"]:
        for net in path["Nets"]:
            net["VC"] = 1
    (out / "topology.ncr").write_text(json.dumps(ncr, indent=2) + "\n")

source_packets = []
for source_index in range(2):
    frames = []
    for sequence in range(test_args.packets_per_source):
        size = sizes[sequence % len(sizes)]
        frames.append(bytes([0xA0 + source_index * 16])
                      + sequence.to_bytes(4, "big")
                      + bytes((i + source_index * 64 + sequence) % 256
                              for i in range(size - 5)))
    source_packets.append(frames)
    (out / f"source{source_index}.txt").write_text(
        "".join(f"{7 if test_args.tdest_aliases and index % 2 else 0} "
                + frame.hex() + "\n" for index, frame in enumerate(frames)))
packets = [packet for frames in source_packets for packet in frames]
(out / "expected.txt").write_text("".join(packet.hex() + "\n" for packet in packets))
sources = []
sink = None


def make_nsu(tile, options):
    global sink
    if tile != "M00_AXIS_nsu":
        raise ValueError(f"Unexpected NSU {tile}")
    sink = AxisPacketCheckerSink(
        data_width=512, tid_width=6, tdest_width=10,
        check_mode="bytes", expected_packet_file=str(out / "expected.txt"),
        expected_packets=len(packets), unordered_packets=True, fail_fast=False,
        ready_percent=test_args.sink_ready_percent,
        capture_packet_file=str(out / "capture.txt"))
    return sink


def make_nmu(tile, options):
    if tile not in ("S00_AXIS_nmu", "S01_AXIS_nmu"):
        raise ValueError(f"Unexpected NMU {tile}")
    index = 0 if tile == "S00_AXIS_nmu" else 1
    source = AxisPacketTrafficGenerator(
        data_width=512, tid_width=6, tdest_width=10,
        tid=4 + (index if test_args.different_tids else 0),
        packet_file=str(out / f"source{index}.txt"),
        max_packets=test_args.packets_per_source,
        min_gap_cycles=0, max_gap_cycles=0)
    sources.append(source)
    return source


# Control's sim_cycles limit is compared with ticks, despite its name. Leave
# 5 ms for large frames and backpressure; successful traffic exits immediately.
sys.argv += ["--sim-cycles", "5000000000", "--abs-max-tick", "5000000000"]
aliases = [(source, 7, "M00_AXIS_nsu")
           for source in ("S00_AXIS_nmu", "S01_AXIS_nmu")]
run_axis_test(str(out / "topology"), make_nsu, make_nmu,
              axis_tdest_aliases=aliases if test_args.tdest_aliases else None)
received = [bytes.fromhex(line.split(maxsplit=1)[1])
            for line in (out / "capture.txt").read_text().splitlines()]
emitted = [source.emittedPackets() for source in sources]
network_pending = Root.getInstance().system.noc.network.hasOutstandingTransactions()
expected_order = {}
received_order = {}
for source, frames in enumerate(source_packets):
    for sequence, _ in enumerate(frames):
        tdest = 7 if test_args.tdest_aliases and sequence % 2 else 0
        expected_order.setdefault((source, tdest), []).append(sequence)
for packet in received:
    if len(packet) < 5 or packet[0] not in (0xA0, 0xB0):
        continue
    source = (packet[0] - 0xA0) // 16
    sequence = int.from_bytes(packet[1:5], "big")
    tdest = 7 if test_args.tdest_aliases and sequence % 2 else 0
    received_order.setdefault((source, tdest), []).append(sequence)
stream_order_preserved = received_order == expected_order
passed = (all(source.finished() for source in sources)
          and emitted == [test_args.packets_per_source] * 2
          and sink.receivedPackets() == len(packets) and sink.validationErrors() == 0
          and sink.unmatchedPackets() == 0 and not sink.hasPartialPacket()
          and not network_pending
          and stream_order_preserved
          and Counter(received) == Counter(packets))
result = {
    "pass": passed,
    "tids": [4, 5 if test_args.different_tids else 4],
    "tdest_aliases": test_args.tdest_aliases,
    "shared_vc": test_args.shared_vc,
    "emitted_packets": emitted,
    "expected_packets": len(packets),
    "sink_ready_percent": test_args.sink_ready_percent,
    "completed_frame_slots": test_args.complete_frame_slots,
    "received_packets": sink.receivedPackets(),
    "validation_errors": sink.validationErrors(),
    "unmatched_packets": sink.unmatchedPackets(),
    "partial_packet": sink.hasPartialPacket(),
    "network_pending": network_pending,
    "stream_order_preserved": stream_order_preserved,
    "expected_lengths": [len(packet) for packet in packets],
    "received_lengths": [len(packet) for packet in received],
    "placements": placement["placements"],
}
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("AXIS_SHARED_NSU_FRAME_RESULT", json.dumps(result), flush=True)
sys.exit(0 if passed else 1)
