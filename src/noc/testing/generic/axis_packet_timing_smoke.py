"""Check packet timing capture using real NoC handshakes and backpressure.

Run from Naviq with a build that includes the packet timing capture API:
  build/X86/gem5.opt -r --outdir=m5out/axis-timing-replay \\
    src/noc/testing/generic/axis_packet_timing_smoke.py
  PACKET_CAPTURE_MODE=generated build/X86/gem5.opt -r \\
    --outdir=m5out/axis-timing-generated \\
    src/noc/testing/generic/axis_packet_timing_smoke.py

The default replay mode sends 20 literal frames of varying lengths; generated
mode sends 20 IPv4/UDP packets with 512-byte payloads. Both use 5% sink readiness
and zero packet gaps to exercise source and sink backpressure. The test checks
packet bytes, handshake timestamps, distinct offered-beat accounting, and
end-to-end latency, then writes result.json and packet_metrics.json. Python
assertions must remain enabled. The test does not instantiate PE RTL.
"""
import json
import os
from pathlib import Path
import sys

import m5
from m5.objects import AxisPacketCheckerSink, AxisPacketTrafficGenerator

repo = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(repo / 'src/noc/testing/smartnic/common'))
sys.path.insert(0, str(repo / 'src/noc/testing/smartnic/pe13'))
sys.path.insert(0, str(repo / 'src/noc/setup/include'))
from smartnic_common import run_axis_test
from packet_metrics import build_metrics, read_timing_captures

out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)
mode = os.environ.get('PACKET_CAPTURE_MODE', 'replay')
if mode not in ('replay', 'generated'):
    raise ValueError('PACKET_CAPTURE_MODE must be replay or generated')
count = 20
payloads = [n.to_bytes(4, 'little') + bytes(i % 256 for i in range([37, 130, 517, 65][n % 4] - 4))
            for n in range(count)]
(out / 'source.txt').write_text(''.join(f'{17 if n % 2 else 19} {packet.hex()}\n' for n, packet in enumerate(payloads)))
(out / 'expected.txt').write_text(''.join(packet.hex() + '\n' for packet in reversed(payloads)))
(out / 'empty.txt').write_text('')
source = sink = None

def make_nmu(tile, options):
    global source
    if tile != 'S00_AXIS_nmu':
        return AxisPacketTrafficGenerator(packet_file=str(out / 'empty.txt'), max_packets=0)
    params = dict(max_packets=count, wait_for_start=True, initial_gap_cycles=3,
                  min_gap_cycles=0, max_gap_cycles=0,
                  packet_timing_file=str(out / 'source_timing.jsonl'), endpoint_index=0)
    if mode == 'replay':
        params['packet_file'] = str(out / 'source.txt')
    else:
        params.update(profile='ipv4_udp', min_payload_bytes=512, max_payload_bytes=512,
                      flow_count=count, tdest=17)
    source = AxisPacketTrafficGenerator(**params)
    return source

def make_nsu(tile, options):
    global sink
    if tile != 'M00_AXIS_nsu':
        return AxisPacketCheckerSink(check_mode='bytes', expected_packets=0)
    params = dict(expected_packets=count, ready_percent=5,
                  packet_timing_file=str(out / 'sink_timing.jsonl'), endpoint_index=0,
                  capture_packet_file=str(out / 'sink_packets.txt'))
    if mode == 'replay':
        params.update(check_mode='bytes', unordered_packets=True,
                      expected_packet_file=str(out / 'expected.txt'))
    else:
        params['check_mode'] = 'ipv4'
    sink = AxisPacketCheckerSink(**params)
    return sink

original_instantiate = m5.instantiate
start = None

def instantiate():
    global start
    original_instantiate()
    m5.simulate(50000)
    assert source.emittedPackets() == sink.receivedPackets() == 0
    assert json.loads(source.trafficMetrics())['bytes_offered'] == 0
    start = int(m5.curTick())
    source.start()

m5.instantiate = instantiate
sys.argv += ['--sys-clock', '400MHz', '--noc-clock', '1GHz',
             '--sim-cycles', '30000000', '--abs-max-tick', '5000000000']
run_axis_test(str(repo / 'src/noc/testing/fixtures/topologies/2to2_axis/2to2_axis'), make_nsu, make_nmu,
              axis_tdest_aliases=[('S00_AXIS_nmu', 17, 'M00_AXIS_nsu'), ('S00_AXIS_nmu', 19, 'M00_AXIS_nsu')])
ingress, ingress_errors = read_timing_captures([out / 'source_timing.jsonl'])
egress, egress_errors = read_timing_captures([out / 'sink_timing.jsonl'])
assert not ingress_errors and not egress_errors
assert source.finished() and source.emittedPackets() == sink.receivedPackets() == count
assert len(ingress) == len(egress) == count
if mode == 'replay':
    assert [packet['hex'] for packet in ingress] == [packet.hex() for packet in payloads]
assert sorted(packet['hex'] for packet in ingress) == sorted(packet['hex'] for packet in egress)
assert [packet['packet_index'] for packet in ingress] == list(range(count))
assert [packet['packet_index'] for packet in egress] == list(range(count))
for packets in (ingress, egress):
    for packet in packets:
        assert packet['first_offered_tick'] <= packet['first_beat_tick'] <= packet['last_beat_tick']
        assert packet['last_offered_tick'] <= packet['last_beat_tick']
        assert packet['accepted_beats'] == (packet['bytes'] + 63) // 64
source_metrics = json.loads(source.trafficMetrics())
sink_metrics = json.loads(sink.trafficMetrics())
for snapshot in (source_metrics, sink_metrics):
    assert snapshot['bytes_offered'] == snapshot['bytes_accepted']
    assert snapshot['beats_offered'] == snapshot['beats_accepted']
    assert snapshot['valid_cycles'] == snapshot['beats_accepted'] + snapshot['backpressure_cycles']
    assert not snapshot['partial_packet']
assert source_metrics['backpressure_cycles'] > 0, source_metrics
assert sink_metrics['backpressure_cycles'] > 0, sink_metrics
inputs = [dict(flow_id=n, route_id=0, hex=packet['hex'], source_index=0, source_packet_index=n)
          for n, packet in enumerate(ingress)]
outputs = [dict(flow_id=n, route_id=0, hex=packet['hex'], input_indices=[n], output_flow_id=f'{n}:0')
           for n, packet in enumerate(ingress)]
metrics = build_metrics(inputs, outputs, ingress, egress, window_start_tick=start,
                        window_end_tick=max(packet['last_beat_tick'] for packet in egress) + 2500,
                        ingress_endpoint_metrics=[source_metrics], egress_endpoint_metrics=[sink_metrics])
assert not metrics['errors'], metrics['errors']
assert metrics['aggregate']['latency']['sample_count'] == count
assert metrics['aggregate']['latency']['min_ns'] > 0
(out / 'packet_metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
result = dict(mode=mode, packets=count, pass_=True, source=source_metrics, sink=sink_metrics,
              latency=metrics['aggregate']['latency'])
(out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print('PACKET_CAPTURE_PASS', json.dumps(result))
