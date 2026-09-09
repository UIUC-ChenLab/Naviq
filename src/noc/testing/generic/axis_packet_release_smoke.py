"""Check absolute replay releases on real direct AXIS wires.

From Naviq, after rebuilding gem5:
  build/X86/gem5.fast --outdir=m5out/axis-release \
    src/noc/testing/generic/axis_packet_release_smoke.py

The same replay runs through an always-ready checker and through the existing
deterministic backpressure shim. The shim checks every stalled sideband. A
third, unscheduled replay verifies compatibility. --invalid length|order|gaps|
generated|overflow intentionally fails with a packet_release_ticks diagnostic.
"""

import argparse
import json
from pathlib import Path
import sys

import m5
from m5.objects import (AxisBackpressureShimNode, AxisPacketCheckerSink,
                        AxisPacketTrafficGenerator, Root)


REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src/noc/testing/smartnic/common"))
sys.path.insert(0, str(REPO / "src/noc/setup/include"))
from smartnic_common import run_axis_test

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--invalid", choices=("length", "order", "gaps", "generated", "overflow"))
args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]
out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)
CLOCK = 2500
COUNT = 64
frames = [index.to_bytes(4, "big") + bytes(
    (index * 29 + byte) % 256 for byte in range((64, 66, 130, 257)[index % 4] - 4))
    for index in range(COUNT)]
# Duplicate release times are legal; an idle interval checks that unfinished
# generators wait for future packets instead of ending or releasing them early.
offsets = [0 if index < 4 else index * 2560 for index in range(COUNT)]
offsets = [offset + (2_000_000 if index >= 32 else 0)
           for index, offset in enumerate(offsets)]
(out / "source.txt").write_text("".join(
    f"{14 + index % 4} {frame.hex()} {index % 2}\n"
    for index, frame in enumerate(frames)))
(out / "expected.txt").write_text("".join(frame.hex() + "\n" for frame in frames))
(out / "empty.txt").write_text("")
branches = ("ready", "stalled", "legacy")
sources, sinks = {}, {}
for index, label in enumerate(branches):
    releases = offsets if label != "legacy" else []
    params = dict(packet_file=str(out / "source.txt"), max_packets=COUNT,
                  packet_release_ticks=releases, wait_for_start=True,
                  min_gap_cycles=0, max_gap_cycles=0, tid=26,
                  data_width=512, tid_width=6, tdest_width=10, tuser_width=1,
                  packet_timing_file=str(out / f"{label}_source.jsonl"),
                  endpoint_index=index, clockDomains=[400],
                  port_endpoint_names=[f"{label}_source"])
    if label == "ready" and args.invalid:
        if args.invalid == "length":
            params["packet_release_ticks"] = offsets[:-1]
        elif args.invalid == "order":
            params["packet_release_ticks"] = [1, 0, *offsets[2:]]
        elif args.invalid == "gaps":
            params["min_gap_cycles"] = 1
        elif args.invalid == "generated":
            params["packet_file"] = ""
        elif args.invalid == "overflow":
            params["packet_release_ticks"] = [*offsets[:-1], (1 << 64) - 1]
    sources[label] = AxisPacketTrafficGenerator(**params)
    sinks[label] = AxisPacketCheckerSink(
        data_width=512, tid_width=6, tdest_width=10, tuser_width=1,
        check_mode="bytes", expected_packet_file=str(out / "expected.txt"),
        expected_packets=COUNT, ready_percent=100,
        packet_timing_file=str(out / f"{label}_sink.jsonl"),
        clockDomains=[400], port_endpoint_names=[f"{label}_sink"])

shim = AxisBackpressureShimNode(
    data_width=512, id_width=6, dest_width=10, expected_packets=COUNT,
    backpressure_enabled=True, backpressure_period=5, backpressure_allow=1,
    backpressure_scope="dma_fed_axis_valid_gated_backpressure_v1", fifo_depth=1,
    metrics_output_path=str(out / "shim.json"), clockDomains=[400, 400],
    port_endpoint_names=["shim_input", "shim_output"])


def make_nmu(tile, options):
    return AxisPacketTrafficGenerator(packet_file=str(out / "empty.txt"), max_packets=0)


def make_nsu(tile, options):
    return AxisPacketCheckerSink(check_mode="bytes", expected_packets=0)


original_instantiate = m5.instantiate
original_simulate = m5.simulate
epoch = None
midpoint = None
exit_causes = []


def capture_simulate(*positional, **keywords):
    event = original_simulate(*positional, **keywords)
    exit_causes.append(event.getCause())
    return event


def instantiate():
    global epoch, midpoint
    system = Root.getInstance().system
    system.release_sources = [sources[label] for label in branches]
    system.release_sinks = [sinks[label] for label in branches]
    system.release_shim = shim
    control = system.control
    extra = [*system.release_sources, *system.release_sinks, shim]
    control.nodes = list(control.nodes) + extra
    control.adjacency_index = list(control.adjacency_index) + [
        len(control.adjacency_list)] * len(extra)
    wires = [
        (sources["ready"], "ready_source", sinks["ready"], "ready_sink"),
        (sources["legacy"], "legacy_source", sinks["legacy"], "legacy_sink"),
        (sources["stalled"], "stalled_source", shim, "shim_input"),
        (shim, "shim_output", sinks["stalled"], "stalled_sink")]
    control.direct_sources = [source for source, _, _, _ in wires]
    control.direct_source_ports = [port for _, port, _, _ in wires]
    control.direct_targets = [target for _, _, target, _ in wires]
    control.direct_target_ports = [port for _, _, _, port in wires]
    original_instantiate()
    # Start off the 400 MHz edge to check correct release quantization.
    original_simulate(50001)
    for source in sources.values():
        assert source.emittedPackets() == 0
        assert json.loads(source.trafficMetrics())["bytes_offered"] == 0
    epoch = int(m5.curTick())
    for source in sources.values():
        source.start()
    if args.invalid:
        raise AssertionError(f"Invalid release schedule was accepted: {args.invalid}")
    original_simulate(500_000)
    midpoint = json.loads(sources["stalled"].trafficMetrics())
    # A repeated start must not postpone the remaining scheduled packets.
    for source in sources.values():
        source.start()


m5.instantiate = instantiate
m5.simulate = capture_simulate
sys.argv += ["--sys-clock", "400MHz", "--noc-clock", "1GHz",
             "--sim-cycles", "100000000", "--abs-max-tick", "100000000"]
run_axis_test(str(REPO / "src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis"),
              make_nsu, make_nmu)

captures, metrics = {}, {}
for label in branches:
    source_records = [json.loads(line) for line in
                      (out / f"{label}_source.jsonl").read_text().splitlines()]
    sink_records = [json.loads(line) for line in
                    (out / f"{label}_sink.jsonl").read_text().splitlines()]
    captures[label] = source_records
    metrics[label] = json.loads(sources[label].trafficMetrics())
    assert sources[label].finished() and sources[label].emittedPackets() == COUNT
    assert sinks[label].receivedPackets() == COUNT
    assert not sinks[label].validationErrors() and not sinks[label].hasPartialPacket()
    assert [r["hex"] for r in source_records] == [frame.hex() for frame in frames]
    assert [r["hex"] for r in sink_records] == [frame.hex() for frame in frames]
    previous_last = -CLOCK
    for index, (source, sink) in enumerate(zip(source_records, sink_records)):
        assert source["packet_index"] == index
        assert source["first_offered_tick"] <= source["first_beat_tick"] <= source["last_beat_tick"]
        assert source["last_offered_tick"] <= source["last_beat_tick"]
        assert source["accepted_beats"] == (len(frames[index]) + 63) // 64
        if label != "legacy":
            release = epoch + offsets[index]
            assert source["scheduled_release_tick"] == release
            assert source["first_offered_tick"] >= release
            queue = source["first_offered_tick"] - release
            head_stall = source["first_beat_tick"] - source["first_offered_tick"]
            transport = sink["last_beat_tick"] - source["first_beat_tick"]
            assert queue + head_stall + transport == sink["last_beat_tick"] - release
            if label == "ready":
                first_edge = max(((release + CLOCK - 1) // CLOCK) * CLOCK,
                                 previous_last + CLOCK)
                assert source["first_offered_tick"] == source["first_beat_tick"] == first_edge
                assert source["last_beat_tick"] == first_edge + (source["accepted_beats"] - 1) * CLOCK
        else:
            assert "scheduled_release_tick" not in source
        if label != "stalled":
            for field in ("first_beat_tick", "last_beat_tick", "bytes", "accepted_beats"):
                assert source[field] == sink[field]
        previous_last = source["last_beat_tick"]
    if label != "legacy":
        assert metrics[label]["release_epoch_tick"] == epoch
        assert metrics[label]["packets_released"] == COUNT
        assert metrics[label]["released_packets_pending"] == 0
        assert metrics[label]["released_packets_not_offered"] == 0
    else:
        assert "release_epoch_tick" not in metrics[label]

assert midpoint["packets_released"] == 32
assert midpoint["released_packets_not_offered"] > 0
assert midpoint["released_packets_pending"] > 0
stalls = {"first": 0, "middle": 0, "last": 0}
for packet in captures["stalled"]:
    if packet["accepted_beats"] < 3:
        continue
    head = (packet["first_beat_tick"] - packet["first_offered_tick"]) // CLOCK
    tail = (packet["last_beat_tick"] - packet["last_offered_tick"]) // CLOCK
    stalls["first"] += head
    stalls["last"] += tail
    stalls["middle"] += packet["backpressure_cycles"] - head - tail
assert all(value > 0 for value in stalls.values()), stalls
shim_metrics = json.loads((out / "shim.json").read_text())
assert not shim_metrics["axis_stability_violation"]
assert shim_metrics["shim_input_bytes"] == shim_metrics["shim_output_bytes"] == sum(map(len, frames))
assert not Root.getInstance().system.noc.network.hasOutstandingTransactions()
assert exit_causes[-1] == "Reads and writes completed", exit_causes
result = dict(pass_=True, packets_per_branch=COUNT, epoch=epoch,
              stalled_beat_positions=stalls, midpoint=midpoint, sources=metrics)
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("AXIS_PACKET_RELEASE_PASS", json.dumps(result))
