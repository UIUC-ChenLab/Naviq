"""Regress mixed-VC arbitration at one physical input with output contention.

Run from Naviq:
  build/X86/gem5.fast --outdir=m5out/normal_input_contention \
    src/noc/testing/generic/axis_mixed_vc_input_contention_smoke.py

At NOC_NPS7575_X5Y0, sources 0/1 share port0_in on VCs1/5 and
request port1_out/port2_out. Source2 competes for port1_out on VC1
through port3_in. Each source has a unique TID and a distinct sink.

These exact paths exposed tail overtaking when the normal allocator granted
multiple VCs from one physical input in one cycle. A later source2 HEAD
passed a source0 TAIL still queued in the crossbar, corrupting packet data.
All paths and payloads are self-contained; no PE, CPU or prior run is needed.
Use --trace 1 to record per-cycle arbitration evidence in the output directory.
"""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import subprocess
import sys
import m5
from m5.objects import AxisPacketTrafficGenerator, AxisSinkNode, Root

REPO = Path(__file__).resolve().parents[4]
out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)
os.environ['NOC_CSV_OUTPUT_DIR'] = str(out/'csv')
for relative in ('src/noc/testing/smartnic/common', 'src/noc/setup/include'):
    sys.path.insert(0, str(REPO/relative))
from smartnic_common import run_axis_test

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--packets', type=int, default=256)
parser.add_argument('--ready', type=int, default=3)
parser.add_argument('--other-ready', type=int, default=100)
parser.add_argument('--gap', type=int, default=0)
parser.add_argument('--offset', type=int, default=0)
parser.add_argument('--sizes', default='140,176,192,1024')
parser.add_argument('--trace', type=int, default=0)
args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]
sizes = [int(value) for value in args.sizes.split(',')]
assert all(64 <= size <= 2048 for size in sizes)
# Physical links are pinned to keep this arbitration regression deterministic.
ROUTES = [{'vc': 1,
  'edges': [('NOC_NMU512_X0Y4', 'req_out', 'NOC_NPS_VNOC_X0Y9', 'port3_in'),
            ('NOC_NPS_VNOC_X0Y9', 'port0_out', 'NOC_NPS_VNOC_X0Y11', 'port2_in'),
            ('NOC_NPS_VNOC_X0Y11', 'port0_out', 'NOC_NPS_VNOC_X0Y13', 'port2_in'),
            ('NOC_NPS_VNOC_X0Y13', 'port0_out', 'NOC_NPS7575_X0Y1', 'port3_in'),
            ('NOC_NPS7575_X0Y1', 'port2_out', 'NOC_NPP_RPTR_X0Y3', 'port0_in'),
            ('NOC_NPP_RPTR_X0Y3', 'port0_out', 'NOC_NCRB_SSIT_X1Y1', 'port1_in'),
            ('NOC_NCRB_SSIT_X1Y1', 'port0_out', 'NOC_NPP_RPTR_X1Y0', 'port0_in'),
            ('NOC_NPP_RPTR_X1Y0', 'port0_out', 'NOC_NPS7575_X5Y0', 'port0_in'),
            ('NOC_NPS7575_X5Y0', 'port1_out', 'NOC_NPS_VNOC_X1Y12', 'port2_in'),
            ('NOC_NPS_VNOC_X1Y12', 'port0_out', 'NOC_NPS_VNOC_X1Y10', 'port2_in'),
            ('NOC_NPS_VNOC_X1Y10', 'port3_out', 'NOC_NSU512_X1Y5', 'req')]},
 {'vc': 5,
  'edges': [('NOC_NMU512_X0Y3', 'req_out', 'NOC_NPS_VNOC_X0Y7', 'port3_in'),
            ('NOC_NPS_VNOC_X0Y7', 'port0_out', 'NOC_NPS_VNOC_X0Y9', 'port2_in'),
            ('NOC_NPS_VNOC_X0Y9', 'port0_out', 'NOC_NPS_VNOC_X0Y11', 'port2_in'),
            ('NOC_NPS_VNOC_X0Y11', 'port0_out', 'NOC_NPS_VNOC_X0Y13', 'port2_in'),
            ('NOC_NPS_VNOC_X0Y13', 'port0_out', 'NOC_NPS7575_X0Y1', 'port3_in'),
            ('NOC_NPS7575_X0Y1', 'port2_out', 'NOC_NPP_RPTR_X0Y3', 'port0_in'),
            ('NOC_NPP_RPTR_X0Y3', 'port0_out', 'NOC_NCRB_SSIT_X1Y1', 'port1_in'),
            ('NOC_NCRB_SSIT_X1Y1', 'port0_out', 'NOC_NPP_RPTR_X1Y0', 'port0_in'),
            ('NOC_NPP_RPTR_X1Y0', 'port0_out', 'NOC_NPS7575_X5Y0', 'port0_in'),
            ('NOC_NPS7575_X5Y0', 'port2_out', 'NOC_NPP_RPTR_X1Y2', 'port0_in'),
            ('NOC_NPP_RPTR_X1Y2', 'port0_out', 'NOC_NCRB_SSIT_X2Y1', 'port0_in'),
            ('NOC_NCRB_SSIT_X2Y1', 'port0_out', 'NOC_NPP_RPTR_X2Y0', 'port0_in'),
            ('NOC_NPP_RPTR_X2Y0', 'port0_out', 'NOC_NPS7575_X6Y0', 'port0_in'),
            ('NOC_NPS7575_X6Y0', 'port1_out', 'NOC_NPS_VNOC_X2Y12', 'port2_in'),
            ('NOC_NPS_VNOC_X2Y12', 'port0_out', 'NOC_NPS_VNOC_X2Y10', 'port2_in'),
            ('NOC_NPS_VNOC_X2Y10', 'port3_out', 'NOC_NSU512_X2Y5', 'req')]},
 {'vc': 1,
  'edges': [('NOC_NMU512_X2Y11', 'req_out', 'NOC_NPS_VNOC_X2Y23', 'port3_in'),
            ('NOC_NPS_VNOC_X2Y23', 'port2_out', 'NOC_NPS_VNOC_X2Y21', 'port0_in'),
            ('NOC_NPS_VNOC_X2Y21', 'port2_out', 'NOC_NPS_VNOC_X2Y19', 'port0_in'),
            ('NOC_NPS_VNOC_X2Y19', 'port2_out', 'NOC_NPS_VNOC_X2Y17', 'port0_in'),
            ('NOC_NPS_VNOC_X2Y17', 'port2_out', 'NOC_NPS_VNOC_X2Y15', 'port0_in'),
            ('NOC_NPS_VNOC_X2Y15', 'port2_out', 'NOC_NPS7575_X6Y3', 'port3_in'),
            ('NOC_NPS7575_X6Y3', 'port0_out', 'NOC_NPP_RPTR_X2Y5', 'port1_in'),
            ('NOC_NPP_RPTR_X2Y5', 'port1_out', 'NOC_NCRB_SSIT_X3Y3', 'port1_in'),
            ('NOC_NCRB_SSIT_X3Y3', 'port0_out', 'NOC_NPP_RPTR_X1Y6', 'port1_in'),
            ('NOC_NPP_RPTR_X1Y6', 'port1_out', 'NOC_NPS7575_X5Y2', 'port2_in'),
            ('NOC_NPS7575_X5Y2', 'port3_out', 'NOC_NIDB_X1Y3', 'port0_in'),
            ('NOC_NIDB_X1Y3', 'port1_out', 'NOC_NIDB_X1Y1', 'port1_in'),
            ('NOC_NIDB_X1Y1', 'port0_out', 'NOC_NPS7575_X5Y0', 'port3_in'),
            ('NOC_NPS7575_X5Y0', 'port1_out', 'NOC_NPS_VNOC_X1Y12', 'port2_in'),
            ('NOC_NPS_VNOC_X1Y12', 'port0_out', 'NOC_NPS_VNOC_X1Y10', 'port2_in'),
            ('NOC_NPS_VNOC_X1Y10', 'port0_out', 'NOC_NPS_VNOC_X1Y8', 'port2_in'),
            ('NOC_NPS_VNOC_X1Y8', 'port0_out', 'NOC_NPS_VNOC_X1Y6', 'port2_in'),
            ('NOC_NPS_VNOC_X1Y6', 'port0_out', 'NOC_NPS_VNOC_X1Y4', 'port2_in'),
            ('NOC_NPS_VNOC_X1Y4', 'port3_out', 'NOC_NSU512_X1Y2', 'req')]}]
placements = {}
connections = {'kind': 'naviq.connections', 'version': 1,
               'name': 'normal_input_contention', 'components': {}, 'connections': []}
for index, route in enumerate(ROUTES):
    placements[f'source{index}.m_axis'] = route['edges'][0][0]
    placements[f'sink{index}.s_axis'] = route['edges'][-1][2]
    connections['components'][f'source{index}'] = {
        'node_type': 'AxisPacketTrafficGenerator',
        'ports': {'m_axis': {'role': 'master', 'protocol': 'axis'}}}
    connections['components'][f'sink{index}'] = {
        'node_type': 'AxisSinkNode',
        'ports': {'s_axis': {'role': 'slave', 'protocol': 'axis'}}}
    connections['connections'].append({'from': f'source{index}.m_axis', 'to': f'sink{index}.s_axis'})
for name, document in [('connections.json', connections), ('placement.json',
                       {'kind': 'naviq.placement', 'version': 1, 'placements': placements})]:
    (out/name).write_text(json.dumps(document, indent=2)+'\n')
with (out/'topology.log').open('w') as log:
    subprocess.run(['python3', str(REPO/'noc_testing/tools/topology/generate_ncr.py'),
                    '--connections', str(out/'connections.json'), '--placement', str(out/'placement.json'),
                    '--nts', str(out/'stress.nts'), '--ncr', str(out/'stress.ncr'),
                    '--router', 'shortest_path'], cwd=REPO, stdout=log, stderr=subprocess.STDOUT, check=True)
ncr = json.loads((out/'stress.ncr').read_text())
for index, route in enumerate(ROUTES):
    path = next(path for path in ncr['Paths']
                if path['From'].endswith(f'/S{index:02d}_AXIS_nmu'))
    assert path['To'].endswith(f'/M{index:02d}_AXIS_nsu')
    assert len(path['Nets']) == 1 and path['Nets'][0]['CommType'] == 'WRITE'
    net = path['Nets'][0]
    net['VC'] = route['vc']
    net['Connections'] = [value for edge in route['edges'] for value in edge]
(out/'stress.ncr').write_text(json.dumps(ncr, indent=2)+'\n')
expected = defaultdict(list)
for index in range(3):
    lines = []
    for sequence in range(args.packets):
        size = sizes[sequence % len(sizes)]
        packet = bytes((offset + 37*index + sequence) % 256 for offset in range(size-12))
        packet += index.to_bytes(4, 'big') + sequence.to_bytes(4, 'big') + size.to_bytes(4, 'big')
        tdest, tid = 10+index, 26+index
        expected[(tid, tdest)].append(packet.hex())
        lines.append(f'{tdest} {packet.hex()}\n')
    (out/f'source{index}.txt').write_text(''.join(lines))
sources = {}
def make_nmu(name, options):
    index = int(name[1:3])
    node = AxisPacketTrafficGenerator(data_width=512, tid_width=6, tdest_width=10,
        tid=26+index, packet_file=str(out/f'source{index}.txt'), max_packets=args.packets,
        min_gap_cycles=args.gap, max_gap_cycles=args.gap,
        initial_gap_cycles=args.offset if index == 2 else 0)
    sources[index] = node
    return node

def make_nsu(name, options):
    index = int(name[1:3])
    return AxisSinkNode(data_width=512, id_width=6, dest_width=10,
        ready_percent=args.ready if index == 0 else args.other_ready,
        expected_packets=args.packets)

original_instantiate = m5.instantiate
def capture_instantiate(*pos, **kw):
    network = Root.getInstance().system.noc.network
    for index in range(3):
        network.netifs[index].axis_tid_width = 6
        network.netifs[index].axis_beat_capture_file = str(out/f'nsu{index}.jsonl')
    network.nps_queue_trace_mode = args.trace
    network.nps_queue_trace_path = str(out/'nps_queue_trace.csv')
    return original_instantiate(*pos, **kw)
m5.instantiate = capture_instantiate
causes = []
original_simulate = m5.simulate
def capture_simulate(*pos, **kw):
    event = original_simulate(*pos, **kw)
    causes.append(event.getCause())
    return event
m5.simulate = capture_simulate
sys.argv += ['--sys-clock', '400MHz', '--noc-clock', '1GHz',
             '--sim-cycles', '5000000000', '--abs-max-tick', '5000000000']
run_axis_test(str(out/'stress'), make_nsu, make_nmu,
              axis_tdest_aliases=[(f'S{i:02d}_AXIS_nmu', 10+i, f'M{i:02d}_AXIS_nsu') for i in range(3)])
errors = []
received = defaultdict(list)
for index in range(3):
    partial = defaultdict(bytearray)
    for line in (out/f'nsu{index}.jsonl').read_text().splitlines():
        beat = json.loads(line)
        key = (beat['tid'], beat['tdest'])
        data = bytes.fromhex(beat['hex'])
        if beat['tkeep'] != (1 << len(data))-1 or (not beat['tlast'] and len(data) != 64):
            errors.append('invalid keep/chop')
        partial[key].extend(data)
        if beat['tlast']:
            received[key].append(partial.pop(key).hex())
    if any(partial.values()):
        errors.append('partial packet')
if dict(received) != dict(expected):
    errors.append('byte/count/per-flow-order mismatch')
emitted = [sources[index].emittedPackets() for index in range(3)]
if emitted != [args.packets]*3:
    errors.append('incomplete source')
pending = Root.getInstance().system.noc.network.hasOutstandingTransactions()
if pending:
    errors.append('outstanding network transactions')
if causes[-1] != 'Reads and writes completed':
    errors.append('non-completion exit')
# The trace stream is flushed by gem5 at process exit, so offline analysis uses
# this exact file for simultaneous physical-input grants and tail/HEAD order.
result = {'pass': not errors, 'errors': errors, 'parameters': vars(args),
          'emitted': emitted, 'received': {f'{t}:{d}': len(p) for (t,d),p in received.items()},
          'tick': m5.curTick(), 'network_pending': pending, 'exit_causes': causes,
          'target_router': 'NOC_NPS7575_X5Y0',
          'vcs': [route['vc'] for route in ROUTES]}
(out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
print('AXIS_MIXED_VC_INPUT_CONTENTION', json.dumps(result))
sys.exit(0 if not errors else 1)
