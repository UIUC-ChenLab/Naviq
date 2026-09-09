"""Check replay dependency gates and legacy batches on real direct AXIS wires.

Run after rebuilding gem5:
  build/X86/gem5.fast --outdir=m5out/axis-dependency \
    src/noc/testing/generic/axis_packet_dependency_smoke.py

This bounded regression checks overdue gates, independent grant IDs, repeated
and rejected grants, stable stalled beats, and ungated dynamic replay batches.
"""
import json
from pathlib import Path
import sys
import m5
from m5.objects import (AxisBackpressureShimNode, AxisPacketCheckerSink,
                        AxisPacketTrafficGenerator, Root)

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / 'src/noc/testing/smartnic/common'))
sys.path.insert(0, str(REPO / 'src/noc/setup/include'))
from smartnic_common import run_axis_test

out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)
COUNT = 16
CLOCK = 2500
frames = [index.to_bytes(4, 'big') + bytes((index*29+byte)%256 for byte in
          range((64, 66, 130, 257)[index%4]-4)) for index in range(COUNT)]
releases = [index*2560 for index in range(COUNT)]
gates = [101 if index in (3, 10) else 202 if index == 8 else 0
         for index in range(COUNT)]
(out/'source.txt').write_text(''.join(
    f'{14+index%4} {frame.hex()} {index%2}\n' for index, frame in enumerate(frames)))
(out/'expected.txt').write_text(''.join(frame.hex()+'\n' for frame in frames))
(out/'legacy_expected.txt').write_text(''.join(frame.hex()+'\n' for frame in frames*2))
(out/'empty.txt').write_text('')
branches = ('ready', 'stalled', 'legacy')
sources, sinks = {}, {}
for index, label in enumerate(branches):
    sources[label] = AxisPacketTrafficGenerator(
        packet_file=str(out/'source.txt'), max_packets=COUNT,
        packet_release_ticks=releases if label != 'legacy' else [],
        packet_dependency_ids=gates if label != 'legacy' else [],
        wait_for_start=True, min_gap_cycles=0, max_gap_cycles=0, tid=26,
        data_width=512, tid_width=6, tdest_width=10, tuser_width=1,
        packet_timing_file=str(out/f'{label}_source.jsonl'), endpoint_index=index,
        clockDomains=[400], port_endpoint_names=[f'{label}_source'])
    sinks[label] = AxisPacketCheckerSink(
        data_width=512, tid_width=6, tdest_width=10, tuser_width=1,
        check_mode='bytes', expected_packet_file=str(out/(
            'legacy_expected.txt' if label == 'legacy' else 'expected.txt')),
        expected_packets=COUNT*(2 if label == 'legacy' else 1), ready_percent=100,
        packet_timing_file=str(out/f'{label}_sink.jsonl'), clockDomains=[400],
        port_endpoint_names=[f'{label}_sink'])
shim = AxisBackpressureShimNode(
    data_width=512, id_width=6, dest_width=10, expected_packets=COUNT,
    backpressure_enabled=True, backpressure_period=5, backpressure_allow=1,
    backpressure_scope='dma_fed_axis_valid_gated_backpressure_v1', fifo_depth=1,
    metrics_output_path=str(out/'shim.json'), clockDomains=[400,400],
    port_endpoint_names=['shim_input','shim_output'])

def make_nmu(tile, options):
    return AxisPacketTrafficGenerator(packet_file=str(out/'empty.txt'), max_packets=0)

def make_nsu(tile, options):
    return AxisPacketCheckerSink(check_mode='bytes', expected_packets=0)

original_instantiate = m5.instantiate
original_simulate = m5.simulate
epoch = None
grants = {}
blocked = {}

def instantiate():
    global epoch
    system = Root.getInstance().system
    system.dependency_sources = [sources[label] for label in branches]
    system.dependency_sinks = [sinks[label] for label in branches]
    system.dependency_shim = shim
    control = system.control
    extra = [*system.dependency_sources, *system.dependency_sinks, shim]
    control.nodes = list(control.nodes)+extra
    control.adjacency_index = list(control.adjacency_index)+[
        len(control.adjacency_list)]*len(extra)
    wires = [(sources['ready'],'ready_source',sinks['ready'],'ready_sink'),
             (sources['legacy'],'legacy_source',sinks['legacy'],'legacy_sink'),
             (sources['stalled'],'stalled_source',shim,'shim_input'),
             (shim,'shim_output',sinks['stalled'],'stalled_sink')]
    control.direct_sources = [a for a,_,_,_ in wires]
    control.direct_source_ports = [b for _,b,_,_ in wires]
    control.direct_targets = [c for _,_,c,_ in wires]
    control.direct_target_ports = [d for _,_,_,d in wires]
    original_instantiate()
    original_simulate(50001)
    epoch = int(m5.curTick())
    for source in sources.values():
        assert source.emittedPackets() == 0
        source.start()
    # Every release is overdue, but neither gated branch can offer packet 3.
    original_simulate(1_000_000)
    for label in ('ready','stalled'):
        source = sources[label]
        metrics = json.loads(source.trafficMetrics())
        assert source.emittedPackets() == 3 and not source.finished(), metrics
        assert metrics['packets_offered'] == 3
        assert metrics['bytes_offered'] == sum(map(len,frames[:3]))
        assert metrics['packets_released'] == COUNT
        blocked[label] = metrics
        for unknown in (0,999):
            try:
                source.grantDependency(unknown)
            except Exception as error:
                assert 'unknown packet dependency ID' in str(error), error
            else:
                raise AssertionError(f'Unknown gate {unknown} accepted')
        source.grantDependency(101)
        source.grantDependency(101)  # An idempotent duplicate grant is valid.
    grants[101] = int(m5.curTick())
    assert sources['legacy'].finished()
    sources['legacy'].startReplayBatch(str(out/'source.txt'), [])
    original_simulate(1_000_000)
    for label in ('ready','stalled'):
        metrics = json.loads(sources[label].trafficMetrics())
        assert sources[label].emittedPackets() == 8 and not sources[label].finished(), metrics
        assert metrics['packets_offered'] == 8
        assert metrics['bytes_offered'] == sum(map(len,frames[:8]))
        sources[label].grantDependency(202)
        sources[label].grantDependency(202)
    grants[202] = int(m5.curTick())

m5.instantiate = instantiate
sys.argv += ['--sys-clock','400MHz','--noc-clock','1GHz',
             '--sim-cycles','100000000','--abs-max-tick','100000000']
run_axis_test(str(REPO/'src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis'),
              make_nsu, make_nmu)

metrics = {}
for label in branches:
    records = [json.loads(line) for line in (out/f'{label}_source.jsonl').read_text().splitlines()]
    received = [json.loads(line) for line in (out/f'{label}_sink.jsonl').read_text().splitlines()]
    expected = frames*(2 if label == 'legacy' else 1)
    assert sources[label].finished() and sources[label].emittedPackets() == len(expected)
    assert sinks[label].receivedPackets() == len(expected)
    assert not sinks[label].validationErrors() and not sinks[label].hasPartialPacket()
    assert [row['hex'] for row in records] == [frame.hex() for frame in expected]
    assert [row['hex'] for row in received] == [frame.hex() for frame in expected]
    for index, record in enumerate(records):
        assert record['first_offered_tick'] <= record['first_beat_tick'] <= record['last_beat_tick']
        if label != 'legacy':
            assert record['scheduled_release_tick'] == epoch+releases[index]
            earliest = epoch+releases[index]
            if index >= 3: earliest = max(earliest,grants[101])
            if index >= 8: earliest = max(earliest,grants[202])
            assert record['first_offered_tick'] >= earliest
        else:
            assert 'scheduled_release_tick' not in record
            assert record['batch_id'] == index//COUNT
    metrics[label] = json.loads(sources[label].trafficMetrics())
assert metrics['stalled']['backpressure_cycles'] > 0
shim_metrics = json.loads((out/'shim.json').read_text())
assert not shim_metrics['axis_stability_violation']
assert shim_metrics['shim_input_bytes'] == shim_metrics['shim_output_bytes'] == sum(map(len,frames))
assert not Root.getInstance().system.noc.network.hasOutstandingTransactions()
result = dict(passed=True, packets=COUNT, grant_ticks=grants, blocked=blocked, sources=metrics)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print('AXIS_PACKET_DEPENDENCY_PASS', json.dumps(result))
