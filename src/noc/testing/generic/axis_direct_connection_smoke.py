"""Check Control's direct AXIS wires, without packetization or a CDC queue.

  build/X86/gem5.fast --outdir=m5out/axis-direct \
    src/noc/testing/generic/axis_direct_connection_smoke.py

Twenty literal frames travel directly from a 400 MHz generator to a checker
with sink backpressure. An unrelated existing NoC pair also sends two frames.
Accepted source/sink packet timestamps must match exactly on the direct wire.
--invalid clock|duplicate|direction intentionally requests an invalid connection
and must cause instantiation to exit nonzero with an appropriate diagnostic.
"""

import argparse
import json
from pathlib import Path
import sys

import m5
from m5.objects import AxisPacketCheckerSink, AxisPacketTrafficGenerator, Root


repo = Path(__file__).resolve().parents[4]
for path in ("src/noc/testing/smartnic/common", "src/noc/setup/include"):
    sys.path.insert(0, str(repo / path))
from smartnic_common import run_axis_test

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--invalid", choices=("clock", "duplicate", "direction"))
args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]
out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)
packets = [index.to_bytes(4, "big") + bytes(
    (byte + index * 31) % 256 for byte in range([65, 1500, 284, 63][index % 4] - 4))
    for index in range(20)]
(out / "direct_source.txt").write_text("".join(f"14 {frame.hex()}\n" for frame in packets))
(out / "direct_expected.txt").write_text("".join(frame.hex() + "\n" for frame in packets))
(out / "noc_source.txt").write_text("".join(f"0 {frame.hex()}\n" for frame in packets[:2]))
(out / "noc_expected.txt").write_text("".join(frame.hex() + "\n" for frame in packets[:2]))
(out / "empty.txt").write_text("")
direct_source = AxisPacketTrafficGenerator(
    data_width=512, tid_width=6, tdest_width=10, tid=26,
    packet_file=str(out / "direct_source.txt"), max_packets=len(packets),
    wait_for_start=True, min_gap_cycles=0, max_gap_cycles=0,
    packet_timing_file=str(out / "direct_source_timing.jsonl"),
    clockDomains=[400], port_endpoint_names=["direct_m_axis"])
direct_sink = AxisPacketCheckerSink(
    data_width=512, tid_width=6, tdest_width=10,
    check_mode="bytes", expected_packet_file=str(out / "direct_expected.txt"),
    expected_packets=len(packets), ready_percent=20, check_tdest=True, tdest=14,
    packet_timing_file=str(out / "direct_sink_timing.jsonl"),
    clockDomains=[500 if args.invalid == "clock" else 400],
    port_endpoint_names=["direct_s_axis"])
noc_sources, noc_sinks = [], []


def make_nmu(tile, options):
    active = tile == "S00_AXIS_nmu"
    node = AxisPacketTrafficGenerator(
        packet_file=str(out / ("noc_source.txt" if active else "empty.txt")),
        max_packets=2 if active else 0, tid=1 if active else 2,
        min_gap_cycles=0, max_gap_cycles=0)
    noc_sources.append(node)
    return node


def make_nsu(tile, options):
    active = tile == "M00_AXIS_nsu"
    node = AxisPacketCheckerSink(
        check_mode="bytes", expected_packets=2 if active else 0,
        expected_packet_file=str(out / ("noc_expected.txt" if active else "empty.txt")))
    noc_sinks.append(node)
    return node


original_instantiate = m5.instantiate
original_simulate = m5.simulate
exit_causes = []


def record_simulate(*simulate_args, **simulate_kwargs):
    event = original_simulate(*simulate_args, **simulate_kwargs)
    exit_causes.append(event.getCause())
    return event


def instantiate():
    system = Root.getInstance().system
    system.direct_source = direct_source
    system.direct_sink = direct_sink
    control = system.control
    control.nodes = list(control.nodes) + [direct_source, direct_sink]
    # Repeated offsets describe nodes with zero associated NoC interfaces.
    control.adjacency_index = list(control.adjacency_index) + [len(control.adjacency_list)] * 2
    control.direct_sources = [direct_source]
    control.direct_targets = [direct_sink]
    control.direct_source_ports = ["direct_m_axis"]
    control.direct_target_ports = ["direct_s_axis"]
    if args.invalid == "duplicate":
        control.direct_sources = [direct_source, direct_source]
        control.direct_targets = [direct_sink, direct_sink]
        control.direct_source_ports = ["direct_m_axis", "direct_m_axis"]
        control.direct_target_ports = ["direct_s_axis", "direct_s_axis"]
    elif args.invalid == "direction":
        control.direct_sources = [direct_sink]
        control.direct_targets = [direct_source]
        control.direct_source_ports = ["direct_s_axis"]
        control.direct_target_ports = ["direct_m_axis"]
    original_instantiate()
    if args.invalid:
        raise AssertionError(f"Control accepted invalid direct connection: {args.invalid}")
    m5.simulate(50000)
    if direct_source.emittedPackets() or direct_sink.receivedPackets():
        raise AssertionError("Direct source injected before explicit start")
    direct_source.start()


m5.instantiate = instantiate
m5.simulate = record_simulate
sys.argv += ["--sys-clock", "400MHz", "--noc-clock", "1GHz",
             "--sim-cycles", "30000000", "--abs-max-tick", "30000000"]
run_axis_test(str(repo / "src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis"),
              make_nsu, make_nmu)

errors = []
captures = [[json.loads(line) for line in (out / f"direct_{side}_timing.jsonl").read_text().splitlines()]
            for side in ("source", "sink")]
metrics = [json.loads(node.trafficMetrics()) for node in (direct_source, direct_sink)]
if not direct_source.finished() or direct_source.emittedPackets() != len(packets):
    errors.append("Direct source did not finish")
if (direct_sink.receivedPackets() != len(packets) or direct_sink.validationErrors()
        or direct_sink.unmatchedPackets() or direct_sink.hasPartialPacket()):
    errors.append("Direct sink packet validation/completion failed")
for side, capture in zip(("source", "sink"), captures):
    if [item["hex"] for item in capture] != [packet.hex() for packet in packets]:
        errors.append(f"Direct {side} capture differs from input packets")
for source, sink in zip(*captures):
    for field in ("first_beat_tick", "last_beat_tick", "accepted_beats", "bytes", "hex"):
        if source[field] != sink[field]:
            errors.append(f"Direct wire changed {field} for packet {source['packet_index']}")
    if source["first_beat_tick"] % 2500 or source["last_beat_tick"] % 2500:
        errors.append("Direct handshake did not occur on the 400 MHz clock")
for snapshot in metrics:
    if not snapshot["backpressure_cycles"]:
        errors.append("Direct test did not exercise backpressure")
    if snapshot["partial_packet"] or snapshot["bytes_offered"] != snapshot["bytes_accepted"]:
        errors.append("Direct endpoint has pending bytes")
for field in ("beats_accepted", "bytes_accepted", "valid_cycles", "backpressure_cycles"):
    if metrics[0][field] != metrics[1][field]:
        errors.append(f"Direct endpoint counters disagree: {field}")
if [node.emittedPackets() for node in noc_sources] != [2, 0]:
    errors.append("Unrelated NoC source counts differ")
if [node.receivedPackets() for node in noc_sinks] != [2, 0]:
    errors.append("Unrelated NoC sink counts differ")
if any(node.validationErrors() or node.hasPartialPacket() for node in noc_sinks):
    errors.append("Unrelated NoC packet validation failed")
if Root.getInstance().system.noc.network.hasOutstandingTransactions():
    errors.append("Outstanding NoC transactions remain")
if not exit_causes or exit_causes[-1] != "Reads and writes completed":
    errors.append("Simulation did not report endpoint completion")
result = {"pass": not errors, "errors": errors, "packets": len(packets),
          "source": metrics[0], "sink": metrics[1], "exit_causes": exit_causes,
          "direct_packet_transport_latency_ticks": 0 if not errors else None}
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("AXIS_DIRECT_CONNECTION_RESULT", json.dumps(result))
sys.exit(0 if not errors else 1)
