"""Regression for AXIS replay, backpressure and cross-destination overtaking.

From Naviq:
  build/X86/gem5.opt --outdir=m5out/axis-replay \
    src/noc/testing/generic/axis_packet_replay_smoke.py

This builds a small topology with one source and two differently placed sinks.
Each sink checks bytes in order; the combined arrival order must differ from
injection order, exercising the monitor's separate destination queues.
"""
import json
import subprocess
import sys
from pathlib import Path

import m5
from m5.objects import AxisPacketTrafficGenerator, AxisPacketCheckerSink

repo = Path(__file__).resolve().parents[4]
for path in ("src/noc/testing/smartnic/common", "src/noc/setup/include"):
    sys.path.insert(0, str(repo / path))
from smartnic_common import run_axis_test

out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)
connections = {
    "kind": "naviq.connections", "version": 1, "name": "axis_replay",
    "components": {
        "source": {"node_type": "AxisPacketTrafficGenerator", "ports": {
            "m_axis": {"role": "master", "protocol": "axis"}}},
        "far": {"node_type": "AxisPacketCheckerSink", "ports": {
            "s_axis": {"role": "slave", "protocol": "axis"}}},
        "near": {"node_type": "AxisPacketCheckerSink", "ports": {
            "s_axis": {"role": "slave", "protocol": "axis"}}},
    },
    "connections": [{"from": "source.m_axis", "to": "far.s_axis"},
                    {"from": "source.m_axis", "to": "near.s_axis"}],
}
placement = {
    "kind": "naviq.placement", "version": 1, "name": "axis_replay",
    "placements": {
        "source.m_axis": "NOC_NMU512_X0Y18",
        "far.s_axis": "NOC_NSU512_X3Y0",
        "near.s_axis": "NOC_NSU512_X0Y17",
    },
}
for filename, content in (("connections.json", connections), ("placement.json", placement)):
    (out / filename).write_text(json.dumps(content, indent=2) + "\n")
with (out / "topology.log").open("w") as log:
    subprocess.run([
        "python3", str(repo / "noc_testing/tools/topology/generate_ncr.py"),
        "--connections", str(out / "connections.json"),
        "--placement", str(out / "placement.json"),
        "--nts", str(out / "topology.nts"), "--ncr", str(out / "topology.ncr"),
        "--router", "shortest_path",
    ], cwd=repo, stdout=log, stderr=subprocess.STDOUT, check=True)

packets = [bytes([i]) + bytes(range(129)) for i in range(20)]
source_file = out / "source.txt"
source_file.write_text("".join(
    f"{i % 2} {packet.hex()}\n" for i, packet in enumerate(packets)))
sinks = []
source = None


def make_nsu(tile, options):
    index = 0 if tile == "M00_AXIS_nsu" else 1
    expected_file = out / f"expected{index}.txt"
    expected_file.write_text("".join(
        packet.hex() + "\n" for packet in packets[index::2]))
    sink = AxisPacketCheckerSink(
        data_width=512, tid_width=16, tdest_width=12,
        check_mode="bytes", expected_packet_file=str(expected_file),
        expected_packets=10, unordered_packets=False,
        ready_percent=25 if index == 0 else 100,
        capture_packet_file=str(out / f"capture{index}.txt"))
    sinks.append(sink)
    return sink


def make_nmu(tile, options):
    global source
    source = AxisPacketTrafficGenerator(
        data_width=512, tid_width=16, tdest_width=12,
        packet_file=str(source_file), max_packets=20,
        min_gap_cycles=0, max_gap_cycles=0)
    return source


sys.argv += ["--sim-cycles", "30000000", "--abs-max-tick", "5000000000"]
run_axis_test(str(out / "topology"), make_nsu, make_nmu)
assert source.finished() and source.emittedPackets() == 20
assert [sink.receivedPackets() for sink in sinks] == [10, 10]
assert all(sink.validationErrors() == 0 and sink.unmatchedPackets() == 0
           for sink in sinks)
arrivals = []
for index in range(2):
    captured = [(int(line.split()[0]), bytes.fromhex(line.split()[1]))
                for line in (out / f"capture{index}.txt").read_text().splitlines()]
    assert [packet for _, packet in captured] == packets[index::2]
    arrivals += [(tick, packet[0]) for tick, packet in captured]
order = [packet for _, packet in sorted(arrivals)]
assert order != list(range(20)), "Test did not exercise cross-destination overtaking"
result = {"result": "pass", "emitted": 20, "received": [10, 10],
          "errors": 0, "arrival_order": order}
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("AXIS_MONITOR_REORDER_PASS", json.dumps(result))
