"""Exercise replay reloads on real AXIS wires, without PE RTL.

Run from Naviq after its normal gem5 build:
  build/X86/gem5.fast --outdir=m5out/axis-batch \
    src/noc/testing/generic/axis_packet_batch_smoke.py

The sink expects the complete multi-batch inventory, so finished warm-up
generators must not cause an intermediate Control termination. The existing
backpressure shim checks all stalled beat sidebands. Invalid reloads must
raise a Python exception and leave the source metrics byte-for-byte unchanged.
"""

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

out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)
CLOCK = 2500


def frame(index, size):
    return index.to_bytes(4, "big") + bytes(
        (index * 29 + byte) % 256 for byte in range(size - 4))


batches = [[frame(0, 130)], [frame(1, 257)],
           [frame(index + 2, (130, 66, 64, 257)[index % 4]) for index in range(64)],
           [frame(66, 130), frame(67, 64)]]
offsets = [[0], [3 * CLOCK + 1],
           [0 if index < 4 else index * CLOCK + (500_000 if index >= 32 else 0)
            for index in range(64)], []]
inventory = [packet for batch in batches for packet in batch]
paths = []
for index, batch in enumerate(batches):
    path = out / f"batch{index}.txt"
    # Omitted TUSER uses the configured default; explicit decimal/hex overrides
    # exercise the unchanged replay grammar on subsequent batches.
    path.write_text("".join(f"17 {packet.hex()}" +
                            ("\n" if index == 0 else
                             f" {hex(number % 2) if number % 3 else number % 2}\n")
                            for number, packet in enumerate(batch)))
    paths.append(path)
(out / "expected.txt").write_text("".join(packet.hex() + "\n" for packet in inventory))
(out / "legacy_expected.txt").write_text("".join(packet.hex() + "\n"
    for packet in [*batches[0], *batches[3]]))
(out / "empty.txt").write_text("")
(out / "bad_after_valid.txt").write_text(paths[0].read_text() + "17 zz\n")
for label, contents in {
    "odd_hex": "17 abc\n", "bad_dest": "1024 aa\n", "bad_user": "17 aa 2\n",
    "extra_field": "17 aa 0 extra\n", "missing_hex": "17\n",
}.items():
    (out / f"{label}.txt").write_text(contents)

common = dict(wait_for_start=True, min_gap_cycles=0, max_gap_cycles=0,
              tid=26, tdest=17, tuser=1, data_width=512, tid_width=6,
              tdest_width=10, tuser_width=1, clockDomains=[400])
source = AxisPacketTrafficGenerator(
    **common, packet_file=str(paths[0]), max_packets=1,
    packet_release_ticks=offsets[0], packet_timing_file=str(out / "source.jsonl"),
    port_endpoint_names=["batch_source"])
legacy_args = dict(common, initial_gap_cycles=2, min_gap_cycles=2, max_gap_cycles=2)
legacy = AxisPacketTrafficGenerator(
    **legacy_args, packet_file=str(paths[0]), max_packets=1,
    packet_timing_file=str(out / "legacy_source.jsonl"),
    port_endpoint_names=["legacy_source"])
generated = AxisPacketTrafficGenerator(
    **common, profile="ipv4_udp", max_packets=2, min_payload_bytes=16,
    max_payload_bytes=16, packet_timing_file=str(out / "generated_source.jsonl"),
    port_endpoint_names=["generated_source"])


def sink(label, count, expected=None):
    return AxisPacketCheckerSink(
        data_width=512, tid_width=6, tdest_width=10, tuser_width=1,
        expected_packets=count, ready_percent=100, check_mode="bytes" if expected else "ipv4",
        check_tdest=True, tdest=17,
        expected_packet_file=str(expected) if expected else "",
        packet_timing_file=str(out / f"{label}.jsonl"),
        clockDomains=[400], port_endpoint_names=[label])


receiver = sink("batch_sink", len(inventory), out / "expected.txt")
legacy_sink = sink("legacy_sink", 3, out / "legacy_expected.txt")
generated_sink = sink("generated_sink", 2)
# Exact checking also covers every sideband. Both replay sources start empty;
# after the generated reference completes they replay its two packets in
# separate batches. One retains default TUSER=1, the other overrides default 0.
sideband_sources = [AxisPacketTrafficGenerator(
    **dict(common, tuser=default), packet_file=str(out / "empty.txt"), max_packets=0,
    port_endpoint_names=[f"sideband_source_{default}"])
    for default in (0, 1)]
sideband_sinks = [AxisPacketCheckerSink(
    data_width=512, tid_width=6, tdest_width=10, tuser_width=1,
    check_mode="exact", profile="ipv4_udp", expected_packets=2,
    min_payload_bytes=16, max_payload_bytes=16, tid=26, tdest=17, tuser=1,
    ready_percent=25, clockDomains=[400], port_endpoint_names=[f"sideband_sink_{default}"])
    for default in (0, 1)]
shim = AxisBackpressureShimNode(
    data_width=512, id_width=6, dest_width=10, expected_packets=len(inventory),
    backpressure_enabled=True, backpressure_period=7, backpressure_allow=1,
    backpressure_scope="dma_fed_axis_valid_gated_backpressure_v1", fifo_depth=1,
    clockDomains=[400, 400], port_endpoint_names=["shim_input", "shim_output"])
original_instantiate, original_simulate = m5.instantiate, m5.simulate
epochs = []
rejections = []
stalled_phases = set()


def metrics(node=source):
    return json.loads(node.trafficMetrics())


def reject(label, node, path, releases):
    before = node.trafficMetrics()
    before_finished, before_emitted = node.finished(), node.emittedPackets()
    try:
        node.startReplayBatch(str(path), releases)
    except (ValueError, RuntimeError, TypeError, OverflowError):
        pass
    else:
        raise AssertionError(f"Reload was accepted: {label}")
    assert node.trafficMetrics() == before, label
    assert node.finished() == before_finished and node.emittedPackets() == before_emitted, label
    rejections.append(label)


def inspect_stall():
    state = metrics()
    if not state["partial_packet"] or state["beats_offered"] == state["beats_accepted"]:
        return
    packet = inventory[state["packets_accepted"]]
    accepted = state["partial_packet_bytes"]
    phase = "first" if accepted == 0 else "last" if accepted + 64 >= len(packet) else "middle"
    if phase not in stalled_phases:
        reject(f"stalled_{phase}", source, paths[1], [0])
        stalled_phases.add(phase)


def until(predicate):
    for _ in range(20_000):
        if predicate():
            return
        event = original_simulate(CLOCK)
        inspect_stall()
        assert event.getCause() == "simulate() limit reached", event.getCause()
    raise AssertionError("Batch/drain timeout")


def instantiate():
    system = Root.getInstance().system
    extra = [source, legacy, generated, receiver, legacy_sink, generated_sink, shim,
             *sideband_sources, *sideband_sinks]
    system.batch_test_nodes = extra
    control = system.control
    control.nodes = list(control.nodes) + extra
    control.adjacency_index = list(control.adjacency_index) + [len(control.adjacency_list)] * len(extra)
    wires = [(source, "batch_source", shim, "shim_input"),
             (shim, "shim_output", receiver, "batch_sink"),
             (legacy, "legacy_source", legacy_sink, "legacy_sink"),
             (generated, "generated_source", generated_sink, "generated_sink")]
    wires += [(a, f"sideband_source_{default}", b, f"sideband_sink_{default}")
              for default, a, b in zip((0, 1), sideband_sources, sideband_sinks)]
    control.direct_sources = [a for a, _, _, _ in wires]
    control.direct_source_ports = [p for _, p, _, _ in wires]
    control.direct_targets = [b for _, _, b, _ in wires]
    control.direct_target_ports = [p for _, _, _, p in wires]
    original_instantiate()
    original_simulate(50001)
    assert metrics()["packets_offered"] == 0
    reject("not_started", source, paths[1], [0])
    epochs.append(int(m5.curTick()))
    for node in (source, legacy, generated, *sideband_sources):
        node.start()
    reject("active_before_offer", source, paths[1], [0])
    until(lambda: source.finished() and receiver.receivedPackets() == 1 and
          legacy.finished() and legacy_sink.receivedPackets() == 1 and generated.finished())
    assert generated_sink.receivedPackets() == 2
    generated_records = [json.loads(line) for line in
        (out / "generated_source.jsonl").read_text().splitlines()]
    assert len(generated_records) == 2
    for packet_index, record in enumerate(generated_records):
        for default, replay_source in zip((0, 1), sideband_sources):
            replay_path = out / f"sideband_{default}_{packet_index}.txt"
            destination = "17" if packet_index == 0 else "0x11"
            override = (" 1" if packet_index == 0 else " 0x1") if default == 0 else ""
            replay_path.write_text(f"{destination} {record['hex']}{override}\n")
            replay_source.startReplayBatch(str(replay_path), [0])
        until(lambda: all(node.finished() for node in sideband_sources) and
              all(node.receivedPackets() == packet_index + 1 for node in sideband_sinks))
    # These are completed generators, but the full-inventory sinks are pending.
    assert not receiver.hasPartialPacket()
    for label in ("missing", "empty", "bad_after_valid", "odd_hex", "bad_dest",
                  "bad_user", "extra_field", "missing_hex"):
        reject(label, source, out / f"{label}.txt", [])
    reject("schedule_length", source, paths[1], [0, 1])
    reject("schedule_order", source, paths[3], [1, 0])
    reject("schedule_overflow", source, paths[1], [(1 << 64) - 1])
    reject("negative_tick", source, paths[1], [-1])
    reject("generated_source", generated, paths[1], [0])
    reject("scheduled_with_gaps", legacy, paths[1], [0])
    legacy.startReplayBatch(str(paths[3]), [])

    epochs.append(int(m5.curTick()))
    source.startReplayBatch(str(paths[1]), offsets[1])
    assert source.emittedPackets() == 1 and not source.finished()
    reject("waiting_for_release", source, paths[0], [0])
    original_simulate(CLOCK)
    assert source.emittedPackets() == 1
    source.start()  # Existing start() stays idempotent and cannot move this epoch.
    until(lambda: source.finished() and receiver.receivedPackets() == 2 and legacy.finished())
    assert legacy_sink.receivedPackets() == 3
    idle_before = source.trafficMetrics()
    original_simulate(4 * CLOCK)
    assert source.trafficMetrics() == idle_before

    epochs.append(int(m5.curTick()))
    source.startReplayBatch(str(paths[2]), offsets[2])
    until(lambda: source.finished() and receiver.receivedPackets() == 66)
    assert stalled_phases == {"first", "middle", "last"}, stalled_phases
    assert metrics()["packets_scheduled"] == metrics()["packets_released"] == 66
    epochs.append(int(m5.curTick()))
    source.startReplayBatch(str(paths[3]), [])
    assert metrics()["batch_id"] == 3 and metrics()["release_epoch_tick"] is None
    # Let the normal run helper handle the final Control completion event.


m5.instantiate = instantiate
sys.argv += ["--sys-clock", "400MHz", "--noc-clock", "1GHz",
             "--sim-cycles", "100000000", "--abs-max-tick", "100000000"]
run_axis_test(str(REPO / "src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis"),
              lambda *_: AxisPacketCheckerSink(check_mode="bytes", expected_packets=0),
              lambda *_: AxisPacketTrafficGenerator(packet_file=str(out / "empty.txt"), max_packets=0))

records = [json.loads(line) for line in (out / "source.jsonl").read_text().splitlines()]
sink_records = [json.loads(line) for line in (out / "batch_sink.jsonl").read_text().splitlines()]
assert source.finished() and source.emittedPackets() == receiver.receivedPackets() == len(inventory)
assert not receiver.hasPartialPacket() and receiver.validationErrors() == 0
assert [r["hex"] for r in records] == [r["hex"] for r in sink_records] == [p.hex() for p in inventory]
position = 0
for batch_id, batch in enumerate(batches):
    for index, packet in enumerate(batch):
        record = records[position]
        assert record["packet_index"] == position
        assert record["batch_id"] == batch_id and record["batch_packet_index"] == index
        if offsets[batch_id]:
            assert record["scheduled_release_tick"] == epochs[batch_id] + offsets[batch_id][index]
            assert record["first_offered_tick"] >= record["scheduled_release_tick"]
        else:
            assert "scheduled_release_tick" not in record
        assert record["accepted_beats"] == (len(packet) + 63) // 64
        position += 1
final = metrics()
assert final["packets_accepted"] == final["packets_offered"] == len(inventory)
assert final["bytes_accepted"] == final["bytes_offered"] == sum(map(len, inventory))
assert final["beats_accepted"] == final["beats_offered"] == sum((len(p) + 63) // 64 for p in inventory)
assert final["batch_id"] == 3 and final["batch_packets_accepted"] == 2
assert final["released_packets_pending"] == final["released_packets_not_offered"] == 0
assert not final["partial_packet"] and final["backpressure_cycles"] > 0
assert "release_epoch_tick" not in metrics(legacy)
assert "release_epoch_tick" not in metrics(generated)
assert legacy.emittedPackets() == 3 and generated.emittedPackets() == 2
assert all(node.emittedPackets() == 2 for node in sideband_sources)
assert all(node.validationErrors() == 0 and node.receivedPackets() == 2
           for node in sideband_sinks)
(out / "batch_result.json").write_text(json.dumps({
    "status": "PASS", "packet_count": len(inventory), "batch_epochs": epochs,
    "rejected_reloads": rejections, "stalled_phases": sorted(stalled_phases),
    "exact_sideband_packets": 4,
    "metrics": final, "legacy_metrics": metrics(legacy),
    "generated_metrics": metrics(generated)}, indent=2) + "\n")
print(f"PASS: {len(batches)} replay batches, atomic reload validation and all stall positions")
