"""Check AXIS NPP integrity at a shared passthrough output VC.

From Naviq:
  build/X86/gem5.fast --outdir=m5out/axis-same-vc-passthrough \
    src/noc/testing/generic/axis_same_vc_passthrough_smoke.py

Add --sink-ready-percent 17 to exercise sink backpressure. This pure-NoC test
needs no external RTL or PE programming. The placement reproduces the PE13
H2C0/AES-TX0 fan-in: their VC5 paths enter NCRB_SSIT_X5Y2 on different ports,
share its output, then diverge to two loopback NSUs. The first source also
alternates with the NAT NSU. The generated paths must retain this convergence.

Each NMU has a unique fixed TID. Receiving Python checks reconstruct packets
from visible TID/TDEST only; the simulated NSUs keep hardware beat delivery.
Before output-VC ownership was enforced at passthrough routers, the first
H2C0-to-loopback0 frame was corrupted at tick 92500 with this traffic.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys

import m5
from m5.objects import AxisPacketTrafficGenerator, AxisSinkNode, Root


REPO = Path(__file__).resolve().parents[4]
for relative in ("src/noc/testing/smartnic/common", "src/noc/setup/include"):
    sys.path.insert(0, str(REPO / relative))
from smartnic_common import run_axis_test


parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--packets-per-source", type=int, default=256)
parser.add_argument("--sink-ready-percent", type=int, default=100)
parser.add_argument("--gap", type=int, default=0)
args, remaining = parser.parse_known_args()
if args.packets_per_source < 4 or not 1 <= args.sink_ready_percent <= 100 or args.gap < 0:
    raise ValueError("At least four packets, readiness 1..100 and a nonnegative gap are required")
sys.argv = [sys.argv[0], *remaining]
out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)

connections = {
    "kind": "naviq.connections", "version": 1, "name": "axis_same_vc_passthrough",
    "components": {
        name: {"node_type": node_type, "ports": {
            port: {"role": role, "protocol": "axis"}}}
        for name, node_type, port, role in (
            ("h2c0", "AxisPacketTrafficGenerator", "m_axis", "master"),
            ("aes_tx0", "AxisPacketTrafficGenerator", "m_axis", "master"),
            ("nat", "AxisSinkNode", "s_axis", "slave"),
            ("loopback0", "AxisSinkNode", "s_axis", "slave"),
            ("loopback1", "AxisSinkNode", "s_axis", "slave"))
    },
    "connections": [
        {"from": "h2c0.m_axis", "to": "nat.s_axis"},
        {"from": "h2c0.m_axis", "to": "loopback0.s_axis"},
        {"from": "aes_tx0.m_axis", "to": "loopback1.s_axis"}],
}
placement = {
    "kind": "naviq.placement", "version": 1,
    "placements": {
        "h2c0.m_axis": "NOC_NMU512_X0Y3",
        "aes_tx0.m_axis": "NOC_NMU512_X2Y5",
        "nat.s_axis": "NOC_NSU512_X1Y11",
        "loopback0.s_axis": "NOC_NSU512_X3Y10",
        "loopback1.s_axis": "NOC_NSU512_X3Y9"},
}
for filename, document in (("connections.json", connections), ("placement.json", placement)):
    (out / filename).write_text(json.dumps(document, indent=2) + "\n")
with (out / "topology.log").open("w") as log:
    subprocess.run([
        "python3", str(REPO / "noc_testing/tools/topology/generate_ncr.py"),
        "--connections", str(out / "connections.json"),
        "--placement", str(out / "placement.json"),
        "--nts", str(out / "passthrough.nts"),
        "--ncr", str(out / "passthrough.ncr"), "--router", "shortest_path"],
        cwd=REPO, stdout=log, stderr=subprocess.STDOUT, check=True)

topology = json.loads((out / "passthrough.ncr").read_text())
convergence = []
for path in topology["Paths"]:
    for net in path["Nets"]:
        # The full PE13 topology assigns both of these NMUs to VC5. Explicitly
        # preserve that property when generating this smaller topology.
        net["VC"] = 5
        ports = net["Connections"]
        edges = list(zip(ports[0::4], ports[1::4], ports[2::4], ports[3::4]))
        for index, (node, port, _, _) in enumerate(edges):
            if node == "NOC_NCRB_SSIT_X5Y2" and port == "port0_out":
                convergence.append({"source": path["From"], "destination": path["To"],
                                    "input_port": edges[index - 1][3], "output_port": port})
if (len(convergence) != 2 or
        {p["input_port"] for p in convergence} != {"port0_in", "port1_in"} or
        len({p["source"] for p in convergence}) != 2 or
        len({p["destination"] for p in convergence}) != 2):
    raise ValueError(f"Generated topology no longer exercises the shared-VC fan-in: {convergence}")
(out / "passthrough.ncr").write_text(json.dumps(topology, indent=2) + "\n")

# Fixed byte fixtures reproduce the first H2C0 packets of the PE13 failure.
# The trailing eight bytes become source/sequence markers; no IP parsing is
# involved because this regression contains only the NoC.
templates = [bytes.fromhex(value) for value in (
    "4500008c0bdb40004006f8b90a100bdc14100bdcd047a65301000bdb02000bdb50184000"
    "9c34000000000bdb7b7c7d7e7f808182838485868788898a8b8c8d8e8f90919293949596"
    "9798999a9b9c9d9e9fa0a1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8"
    "b9babbbcbdbebfc0c1c2c3c4c5c6c7c8c9cacbcccdcecfd0d1d2d3d4d5d6d7d8d9da",
    "450000b000004000403213630af00fd90bf000010000038900000000000000015ef7ac04"
    "11eb74ee8deb220f28e81e3571fff475b4fc09cf680d1dd80c2af11c1090504b1d0e18f54"
    "6d2503eb9570b9abc10baabd4c04ff29237495034ed86b24943cc92d694f14d57eb5246966"
    "423a8b62195df534014602e7e3e995bb2dab0664be0e0bcf949dea3d50db281203a59f4237"
    "28fad1129417e3d5056238ff435d1c65c63ab1af2caebbc466e8e72811a")]
if list(map(len, templates)) != [140, 176]:
    raise ValueError("Invalid packet byte fixtures")
expected = defaultdict(list)
for source, tid in enumerate((26, 0)):
    lines = []
    for sequence in range(args.packets_per_source):
        destination = (9, 15)[sequence % 2] if source == 0 else 16
        packet = (templates[sequence % 2][:-8] + source.to_bytes(4, "big")
                  + sequence.to_bytes(4, "big"))
        expected[(tid, destination)].append(packet.hex())
        lines.append(f"{destination} {packet.hex()}\n")
    (out / f"source{source}.txt").write_text("".join(lines))

sources = []


def make_nmu(name, options):
    index = {"S00_AXIS_nmu": 0, "S01_AXIS_nmu": 1}[name]
    source = AxisPacketTrafficGenerator(
        data_width=512, tid_width=6, tdest_width=10, tid=(26, 0)[index],
        packet_file=str(out / f"source{index}.txt"), max_packets=args.packets_per_source,
        min_gap_cycles=args.gap, max_gap_cycles=args.gap)
    sources.append(source)
    return source


def make_nsu(name, options):
    destination = {"M00_AXIS_nsu": 9, "M01_AXIS_nsu": 15, "M02_AXIS_nsu": 16}[name]
    return AxisSinkNode(
        data_width=512, id_width=6, dest_width=10,
        ready_percent=args.sink_ready_percent,
        expected_packets=sum(len(packets) for (_, dest), packets in expected.items()
                             if dest == destination))


original_instantiate = m5.instantiate


def capture_instantiate(*positional, **keywords):
    network = Root.getInstance().system.noc.network
    for index in range(3):
        if bool(network.netifs[index].axis_reassemble_frames):
            raise ValueError("Regression requires hardware NSU beat delivery")
        network.netifs[index].axis_tid_width = 6
        network.netifs[index].axis_beat_capture_file = str(out / f"nsu{index}.jsonl")
    return original_instantiate(*positional, **keywords)


m5.instantiate = capture_instantiate
exit_causes = []
original_simulate = m5.simulate


def capture_simulate(*positional, **keywords):
    event = original_simulate(*positional, **keywords)
    exit_causes.append(event.getCause())
    return event


m5.simulate = capture_simulate
sys.argv += ["--sys-clock", "400MHz", "--noc-clock", "1GHz",
             "--sim-cycles", "5000000000", "--abs-max-tick", "5000000000"]
run_axis_test(str(out / "passthrough"), make_nsu, make_nmu, axis_tdest_aliases=[
    ("S00_AXIS_nmu", 9, "M00_AXIS_nsu"), ("S00_AXIS_nmu", 15, "M01_AXIS_nsu"),
    ("S01_AXIS_nmu", 16, "M02_AXIS_nsu")])

errors = []
received = defaultdict(list)
total_beats = 0
for index in range(3):
    partial = defaultdict(bytearray)
    for beat_index, line in enumerate((out / f"nsu{index}.jsonl").read_text().splitlines()):
        beat = json.loads(line)
        total_beats += 1
        key = (beat["tid"], beat["tdest"])
        data = bytes.fromhex(beat["hex"])
        if beat["beat_index"] != beat_index or beat["event"] != "endpoint_fifo_enqueue":
            errors.append(f"NSU {index}: malformed enqueue trace")
        if not 1 <= len(data) <= 64 or beat["bytes"] != len(data):
            errors.append(f"NSU {index}: invalid byte count")
        if beat["tkeep"] != (1 << len(data)) - 1 or (not beat["tlast"] and len(data) != 64):
            errors.append(f"NSU {index}: invalid TKEEP or 64-byte chop")
        if key not in expected or key[1] != (9, 15, 16)[index]:
            errors.append(f"NSU {index}: unexpected visible TID/TDEST {key}")
        partial[key].extend(data)
        if beat["tlast"]:
            received[key].append(partial.pop(key).hex())
    if any(partial.values()):
        errors.append(f"NSU {index}: partial packet remains")
if dict(received) != dict(expected):
    errors.append("Packet bytes, counts or per-visible-stream order differ")
emitted = [source.emittedPackets() for source in sources]
if emitted != [args.packets_per_source] * 2 or not all(source.finished() for source in sources):
    errors.append("Sources did not complete")
network_pending = Root.getInstance().system.noc.network.hasOutstandingTransactions()
if network_pending:
    errors.append("Outstanding NoC transactions remain")
if not exit_causes or exit_causes[-1] != "Reads and writes completed":
    errors.append("Simulation did not report endpoint completion")
result = {
    "pass": not errors, "errors": errors, "parameters": vars(args),
    "convergence": convergence, "vc": 5, "tids": [26, 0],
    "axis_reassemble_frames": False, "packet_sizes": [140, 176],
    "emitted": emitted, "received": {f"{tid}:{dest}": len(packets)
                                      for (tid, dest), packets in received.items()},
    "beats": total_beats, "tick": m5.curTick(), "network_pending": network_pending,
    "exit_causes": exit_causes,
}
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("AXIS_SAME_VC_PASSTHROUGH_RESULT", json.dumps(result))
sys.exit(0 if not errors else 1)
