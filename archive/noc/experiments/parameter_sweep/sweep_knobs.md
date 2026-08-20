# Sweep Knob Inventory

This is a detailed list of parameters we can sweep for the Naviq project. It separates knobs by where they live today and whether they are ready for CSV-driven sweeps.

## Run Metadata

Collect these for every run even though they are not model knobs.

| Knob | Status | Why it matters | First-pass values |
| --- | --- | --- | --- |
| `name` | exposed | Stable join key for gem5, Vivado, plots, and notes. | Descriptive unique string |
| `seed` | model-param | Reproducibility for random traffic and placement decisions. | `1`, `2`, `3` for variance checks |
| topology file id | exposed/topology-input | Ties results to `.nts`, `.ncr`, and topology JSON. | Path or generated topology tag |
| git revision | needs-tooling | Makes results reproducible after code changes. | Current commit hash or dirty marker |
| simulator mode | exposed | Distinguishes `gem5_only`, `vivado_only`, `vivado_then_gem5`, etc. | Existing `noc_sweep.py` modes |
| simulation limit | exposed | Prevents one bad point from hanging the sweep. | `--sim-cycles`, `--abs-max-tick` |
| record mode | exposed instrumentation | Controls whether latency/bandwidth and ready/valid CSVs are emitted. | `--record-mode 0`, `1`, or `2`; use `1` or `2` for diagnostic reruns, not as a behavior sweep knob |

## AXI-MM Traffic Knobs

These are the highest-priority workload knobs because the current project plans already use AXI-MM sizing and placement sweeps.

| Knob | Status | Source | Why it matters | First-pass values |
| --- | --- | --- | --- | --- |
| transaction count | exposed | `--num-packets`; CSV `num_write_transactions_cfg` | Controls run length and statistical confidence. | `100`, `1000`, `10000` |
| offered bandwidth | exposed | `--bandwidth`; CSV `axi_write_bandwidth_cfg_MBps` | Primary load knob for saturation curves. | `100`, `250`, `500`, `800`, `1200`, `1600`, `3200` MB/s |
| write size code | exposed | `--write-size` | gem5 CLI takes log2 bytes. CSV plans should store bytes and convert carefully. | bytes: `8`, `16`, `32`, `64`, `128` |
| burst length | exposed | `--write-length` | Changes packetization and per-transaction amortization. AXI `AWLEN=15` means 16 beats. | `0`, `3`, `7`, `15`, `31` if supported |
| data width | exposed | `--data-width`; CSV `tg_axi_data_width_bits` | Changes bytes per beat and serialization pressure. | `128`, `256`, `512` bits |
| read/write mode | partially exposed | `--direction`; generator `read_write_mode` | Separates write-only from mixed read/write contention. | `WRITE_ONLY`, `READ_ONLY`, `INTERLEAVED`, `SEQUENTIAL` |
| max outstanding writes | model-param/hardcoded | `AxiRandomTrafficGenerator.max_outstanding_writes` | Critical for backpressure and queue buildup. Currently set low in config. | `1`, `2`, `4`, `8`, `16` |
| max write commands | model-param | `AxiRandomTrafficGenerator.max_write_commands` | Alternative to external sim limit for equal work per source. | Match transaction count or `0` |
| address distribution | model-param/hardcoded | `address_distribution` | Controls locality, hot spots, and whether traffic walks memory. | `FIXED`, `UNIFORM`, `INCREMENT` |
| transaction size distribution | model-param | `transaction_size_distribution` | Adds realistic variation around request size. | `FIXED` first, then `UNIFORM` |
| inter-command gap | model-param/hardcoded | `gap_distribution`, `min_gap_cycles`, `max_gap_cycles` | Turns bandwidth limit into bursty or smooth injection. | fixed `0`, fixed `5`, uniform `0..20` |
| AXI ID distribution | model-param | `awid_distribution`, `arid_distribution` | Multiple IDs expose ordering/outstanding behavior. | fixed `0`; uniform `0..3` |
| NSU target selection | model-param/hardcoded | `nsu_selection`, `nsu_index_distribution` | Controls hot-spot vs balanced memory traffic. | `INTERLEAVE`, `ROTATE`, `RANDOM` |
| address alignment | model-param/hardcoded | `align_addresses` | Misalignment can change beat count and realism. | `True`, `False` |

Notes:

- The existing `noc_config.py` AXI-MM setup currently uses incrementing addresses, zero max gap, one outstanding write, and `align_addresses=False` in the common path.
- The existing CSV naming around `axi_write_size_bytes` and `axi_write_len_beats` needs a small cleanup note in future plans: gem5 expects log2 size code and AXI burst length encoding, while humans usually think in bytes and beats.

## AXIS Traffic Knobs

AXIS is useful for network packet style workloads and 100 Gb/s-ish streaming cases from the proposal.

| Knob | Status | Source | Why it matters | First-pass values |
| --- | --- | --- | --- | --- |
| packet count | exposed | `max_packets`; current config maps from `--num-packets` | Run length for stream traffic. | `100`, `1000`, `10000` |
| packet size | model-param/hardcoded | `min_packet_size_bytes`, `max_packet_size_bytes` | Main equivalent of AXI-MM burst size. | fixed `64`, `256`, `512`, `1500` bytes |
| packet size distribution | model-param | `packet_size_distribution` | Models fixed Ethernet frames vs variable payloads. | `FIXED`, `UNIFORM` |
| inter-packet gap | model-param/hardcoded | `gap_distribution`, `min_gap_cycles`, `max_gap_cycles` | Controls smooth vs bursty stream injection. | fixed `0`, fixed `5`, uniform `0..20` |
| `TDEST` range/distribution | model-param/hardcoded | `tdest_distribution`, `min_tdest`, `max_tdest` | Determines destination path for AXIS routing. | fixed single destination first; then multiple `TDEST`s |
| `TID` range/distribution | model-param/hardcoded | `tid_distribution`, `min_tid`, `max_tid` | Can represent flow IDs/classes without QoS behavior. | fixed `0`; uniform small range |
| pcap replay | model-param | `AxisPcapTrafficGenerator` | Lets us test realistic packet traces. | Defer until synthetic AXIS is stable |
| packet profile generator | model-param | `AxisPacketTrafficGenerator` | Generates TCP/UDP-like packets without a pcap. | Defer or use for demo workloads |

## Topology And Placement Knobs

These often matter more than a scalar network parameter because they change hop count, path overlap, and contention points.

| Knob | Status | Source | Why it matters | First-pass values |
| --- | --- | --- | --- | --- |
| endpoint count | topology-input/exposed | topology JSON, `.nts`, `.ncr` | Determines fan-in/fan-out and contention. | `1x1`, `2x2`, `4x4`, `8x8`, `16x16` |
| endpoint placement | topology-input | placement JSON/topology generator | Controls hop distance and shared links. | near, medium, far, all-to-all |
| target endpoint type | topology-input | topology JSON and generated NTS | DDR/HBM/BRAM/NSU type changes latency and realism. | BRAM/NSU first, then DDR/HBM if available |
| source/target mapping | topology-input | address map and `TDEST` map | Controls hot spot vs balanced destination pressure. | one-to-one, all-to-one, all-to-all |
| hop count | derived output | topology graph | Key explanatory variable for latency. | compute per source/dest path |
| path overlap | derived output | topology graph | Predicts congestion before simulation. | count shared links/NPS blocks |
| NPS/router type mix | topology-input | `.ncr`, `NoC_Topology.py` | Different NPS types have different latency/credits. | VNOC/HNOC/RPTR/NCRB/NIDB counts per run |
| generated vs hand topology | exposed/topology-input | `noc_sweep.py`, topology generator | Keeps generated experiments distinct from checked-in examples. | record source path and generator args |

## Routing Knobs

| Knob | Status | Source | Why it matters | First-pass values |
| --- | --- | --- | --- | --- |
| routing algorithm | exposed | `--routing-algorithm` | Switches between table, XY, and custom routing. | `2` custom first; compare `0` if valid |
| custom routing table | topology-input | `custom_routing_table_json` from topology parsing | Main path-control mechanism for Versal-like routes. | Generated by `.ncr` |
| route-to-VC map | topology-input | `route_to_vc_json` from `.ncr` nets | Determines VC use for read/write classes. | Record and inspect per run |
| AXIS `TDEST` map | topology-input | `axis_tdest_map_json` | Determines AXIS destinations. | Record and inspect per run |
| number of virtual networks | exposed | `--number-of-virtual-networks` | Sets protocol class capacity. | Keep default first; sweep later only if needed |

## NoC Microarchitecture Knobs

These are the missing "buffer sizes and such" category. They are central to congestion studies.

| Knob | Status | Source | Why it matters | First-pass values |
| --- | --- | --- | --- | --- |
| `ni_flit_size` | exposed | `--ni-flit-size`, `NocGarnetNetwork.ni_flit_size` | Bytes per flit at the network interface. Affects serialization and packet count. | `8`, `16`, `32`, `64` bytes |
| `vcs_per_vnet` | exposed | `--vcs-per-vnet` | More VCs can reduce head-of-line blocking if routing/VC allocation uses them. | `1`, `2`, `4`, `8` |
| `buffers_per_data_vc` | exposed | `--buffers-per-data-vc`, `NocGarnetNetwork.buffers_per_data_vc` | Data VC depth. Direct queueing/congestion knob. | `1`, `2`, `4`, `8`, `16` |
| `buffers_per_ctrl_vc` | exposed | `--buffers-per-ctrl-vc`, `NocGarnetNetwork.buffers_per_ctrl_vc` | Control VC depth. Important for requests/responses and credit pressure. | `1`, `2`, `4`, `8` |
| `rptr_credits` | exposed | `--rptr-credits`, `NocGarnetNetwork.rptr_credits` | Credit depth for repeater-like NPS blocks. | default `1`; sweep `1`, `2`, `4` |
| `vnoc_credits` | exposed | `--vnoc-credits`, `NocGarnetNetwork.vnoc_credits` | Credit depth for VNOC blocks. | default `5`; sweep `2`, `5`, `8`, `12` |
| `hnoc_credits` | exposed | `--hnoc-credits`, `NocGarnetNetwork.hnoc_credits` | Credit depth for HNOC blocks. | default `7`; sweep `4`, `7`, `12`, `16` |
| `ncrb_credits` | exposed | `--ncrb-credits`, `NocGarnetNetwork.ncrb_credits` | Credit depth for NCRB blocks. | default `12`; sweep `8`, `12`, `16`, `24` |
| `nidb_credits` | exposed | `--nidb-credits`, `NocGarnetNetwork.nidb_credits` | Credit depth for NIDB blocks. | default `14`; sweep `8`, `14`, `20`, `28` |
| router latency | exposed | `--router-latency` | Generic router latency knob. May be superseded by NPS-specific latencies. | `1`, `2`, `4`, `8` cycles |
| link latency | exposed | `--link-latency` | Captures interconnect delay per link. | `0`, `1`, `2`, `4` cycles |
| `rptr_latency` | model-param | `NocGarnetNetwork.rptr_latency` | NPS-specific latency. | default `1`; sweep `1`, `2`, `4` |
| `vnoc_latency` | model-param | `NocGarnetNetwork.vnoc_latency` | NPS-specific latency. | default `2`; sweep `1`, `2`, `4` |
| `hnoc_latency` | model-param | `NocGarnetNetwork.hnoc_latency` | NPS-specific latency. | default `2`; sweep `1`, `2`, `4` |
| `ncrb_latency` | model-param | `NocGarnetNetwork.ncrb_latency` | NPS-specific latency. | default `5`; sweep `3`, `5`, `8` |
| `nidb_latency` | model-param | `NocGarnetNetwork.nidb_latency` | NPS-specific latency. | default `6`; sweep `4`, `6`, `10` |
| NoC clock | exposed | `--noc-clock` | Clocking changes cycles-to-time and bandwidth. | keep default first, then `500MHz`, `1GHz` |
| AXI/Ruby/system clocks | exposed | `--sys-clock`, `--ruby-clock`, `--clk-period` | Endpoint injection and reported time depend on clock ratios. | keep fixed unless studying clock effects |

Implementation note: the buffer and credit knobs already exist in `NocGarnetNetwork.py`, are consumed in C++, and now have CSV/CLI plumbing through `noc_testing/noc_sweep.py` and `src/noc/setup/noc_config_funcs.py`. NPS-latency knobs remain a later behavior-plumbing task.

## NMU/NSU Adapter Knobs

These sit between endpoint traffic and the NoC fabric. They are important because a run can saturate in the NMU/NSU adapter before the routers or links are actually the bottleneck.

### Already Present Or Mostly Present

| Knob | Status | Source | Why it matters | First-pass values |
| --- | --- | --- | --- | --- |
| AXI-MM NMU RROB entries | model-param | `rrob.max_entries`, default `64` | Limits how many read-response reassembly entries the NMU can hold. Larger reads consume multiple 32B entries. | `16`, `32`, `64`, `128` |
| AXI-MM/AXIS adapter data width | exposed/partially exposed | `--data-width`, `NocGarnetNetworkInterface.data_width` | Changes endpoint-side beat width and the adapter upsize/downsize behavior. | `128`, `256`, `512` bits |
| AXI-MM protocol queue count | hardcoded shape | `NocInterface` creates 5 buffers | AR/AW/W/R/B each get a protocol queue. Queue depth is currently infinite unless set. | Keep 5 queues, expose per-channel depth |
| AXIS protocol queue count | hardcoded shape | `NocInterface` creates 1 buffer | AXIS has one stream queue before/after the adapter. | Keep 1 queue, expose depth |
| protocol queue depth | model-param/hardcoded default | `NocMessageBuffer.buffer_size`, default `0` infinite | This is separate from VC buffer depth. It controls endpoint-to-adapter backpressure. | `0`, `1`, `4`, `16`, `64` |
| protocol queue dequeue rate | model-param | `NocMessageBuffer.max_dequeue_rate` | Can model limited adapter drain rate per cycle. | `0` unlimited, `1`, `2`, `4` |
| protocol queue ordering | model-param | `NocMessageBuffer.ordered` | AXI channels probably stay ordered, but this should be recorded. | keep `True` first |
| protocol queue priority | model-param | `NocMessageBuffer.routing_priority` | Could bias AR/AW/W/R/B arbitration if consumed together. | defer unless arbitration needs it |
| AXIS sink readiness | model-param/hardcoded in config | `AxisSinkNode.ready_percent`, currently `100` in `noc_config.py` | Clean way to create downstream backpressure. | `100`, `75`, `50`, `25` |
| AXIS FIFO depth | model-param | `AxisFifoNode.fifo_depth`, `AxisFifoRtlNode.fifo_depth` | Models buffering inside stream endpoints or SmartNIC blocks. | `0`, `4`, `16`, `64`, `1024` |
| AXIS FIFO delay | model-param | `AxisFifoNode.delay` | Adds endpoint pipeline/service delay without changing NoC path. | `0`, `1`, `4`, `16` cycles |
| BRAM-like NSU read/write latency | model-param | `BramEndpoint.read_latency`, `BramEndpoint.write_latency` | Endpoint service time. Useful to separate network latency from memory latency. | `1`, `5`, `20`, `100` cycles |

### Good Candidates To Promote Into Params

| Candidate knob | Current form | Why it matters | First-pass values |
| --- | --- | --- | --- |
| NMU max outstanding reads | hardcoded `< 64` in `mmNocMasterUnit::getAxiRAddrReady` | Limits AR acceptance independent of traffic generator issue rate. | `4`, `8`, `16`, `32`, `64` |
| NMU max outstanding writes | hardcoded `< 64` in `mmNocMasterUnit::getAxiWAddrReady` | Limits AW acceptance and write response aggregation. | `4`, `8`, `16`, `32`, `64` |
| AXI-MM NMU write-buffer capacity | hardcoded `512` bytes in `aximmWriteBuffer` and `getAxiWReady` | Direct W-channel backpressure knob. | `128`, `256`, `512`, `1024`, `2048` bytes |
| AXIS NMU write-buffer capacity | hardcoded `512` bytes in `axisWriteBuffer` | Direct stream ingress backpressure knob. | `128`, `256`, `512`, `1024`, `2048` bytes |
| NPP maximum payload/chunk size | hardcoded `256` bytes in chopping and AXIS payload logic | Changes packetization into NoC flits and how much data is grouped per request. | `64`, `128`, `256` bytes |
| internal flit payload size | effectively `16` bytes in several packing paths | Must usually match `ni_flit_size`; mismatches can hide serialization assumptions. | record first; sweep only after audit |
| RROB entry size | hardcoded `32` bytes | Changes read-response buffering granularity. More invasive than RROB count. | defer |
| NMU write prep fixed overhead | hardcoded `8` cycles in `bufferHeadReadyHandler` | Models adapter packing latency before write flits inject. | `0`, `4`, `8`, `12` cycles |
| NMU read cooldown | hardcoded `4` cycles | Models read-response pacing/order constraints in NMU. | `0`, `2`, `4`, `8` cycles |
| NMU small-read beat delay | hardcoded `6` cycles | Can explain small read latency humps. | `0`, `3`, `6`, `12` cycles |
| AXI-MM NSU request tracker depth | hardcoded `32` entries | Limits outstanding reads/writes accepted at the NSU side. | `8`, `16`, `32`, `64` |
| AXI-MM NSU supported AXI IDs | hardcoded `4` | Limits read response state and active ID concurrency. | `1`, `4`, `8`, `16` |
| NSU read response flits per burst | hardcoded `4` | Adds periodic read-response gaps. Important for bandwidth ceilings. | `1`, `2`, `4`, `8` |
| NSU read sticky gap threshold | hardcoded `16` flits | Adds longer-term periodic gaps in read response injection. | `0` disabled, `8`, `16`, `32` |
| NSU read cooldown | hardcoded `2` cycles | Determines when transient read burst counters reset. | `0`, `1`, `2`, `4` cycles |
| NSU write-response sticky gap threshold | hardcoded `16` responses | Adds periodic B-channel response delay. | `0` disabled, `8`, `16`, `32` |
| AXIMM handler read base delay | hardcoded `1` cycle | Baseline delay before NSU read response messages enter the NoC path. | `0`, `1`, `2`, `4` cycles |
| AXIS ID/dest sideband widths inside stream NSU output | partially hardcoded `6`/`4` in some output beat construction | Should match `axis_id_width` and `axis_dest_width`; could affect correctness before being a sweep. | fix/record first |

### Recommended NMU/NSU Sweep Order

Start with knobs that change backpressure but do not change packet semantics:

1. Protocol queue depth: AR/AW/W/R/B queue `buffer_size`, AXIS queue depth.
2. RROB depth: `rrob.max_entries`.
3. NMU write-buffer capacity.
4. NSU request tracker depth and supported ID count.
5. Response gap/cooldown parameters.
6. NPP size and internal flit packing only after the baseline matches expected behavior.

The cleanest implementation path is to expose adapter knobs as SimObject params first, then add CLI/CSV plumbing. Avoid making them traffic-generator-only knobs, because they describe the NMU/NSU hardware model rather than the workload.

## Endpoint And Memory Knobs

| Knob | Status | Source | Why it matters | First-pass values |
| --- | --- | --- | --- | --- |
| NSU read latency | model-param | `src/noc/endpoints/memory/bram/BramEndpoint.py` | Separates network delay from endpoint service delay. | `1`, `5`, `20` cycles |
| NSU write latency | model-param | `src/noc/endpoints/memory/bram/BramEndpoint.py` | Affects write response timing. | `1`, `5`, `20` cycles |
| NSU memory size/address range | model-param/topology-input | `BramEndpoint.py`, address maps | Controls address mapping and target decode. | record from generated map |
| endpoint data width | exposed/partially exposed | `--data-width`, Vivado plan columns | Serialization at endpoints can dominate small widths. | `128`, `256`, `512` bits |
| AXIS sink readiness | model-param if present in endpoint config | AXIS endpoint models | Direct backpressure source for stream tests. | always-ready first; then 75%, 50% if exposed |

## Outputs To Collect

These are not sweep inputs, but they should be standardized for every run.

| Output | Status | Why it matters |
| --- | --- | --- |
| run manifest | needs-tooling | Captures all knobs, paths, git state, command, start/end time, and pass/fail. |
| stdout/stderr log | exposed | Contains gem5 stats and failure context. |
| per-node latency min/max/avg | exposed | Current headline result for read/write/AXIS behavior. |
| latency percentiles | exposed/derived | Tail latency is often where congestion first appears. |
| achieved read/write bandwidth | exposed | Main throughput metric. |
| fairness metrics | exposed | Existing gem5 result CSVs include JFI, CV, and max/min for read/write bandwidth and latency across AXI-MM NMUs. |
| per-transaction CSVs | exposed when `record_mode=1` | Enables latency distributions and percentile plots. |
| ready/valid CSV | exposed when `record_mode=2` | Measures endpoint-level backpressure and stalls. |
| link-id mapping CSV | exposed | Joins transaction records to source/destination IDs. |
| bandwidth over time | derived | Finds warmup, burstiness, and saturation periods. |
| hop count and path overlap | derived from topology | Helps explain latency and bottlenecks. |
| NPS occupancy trace | exposed with `--nps-occ-trace` | Samples per-NPS/router occupancy by port for hotspot localization. |
| NPS queue trace | exposed with `--nps-queue-trace` | Sparse per-cycle input VC and credit queue depths; useful for queueing and credit-pressure diagnosis. |
| hotspot capture metadata | exposed through `noc_sweep.py --hotspot-mode` | Records whether occupancy/queue traces were requested, copied, empty, or missing for each row. |
| hotspot top1 location/share | exposed/derived | Identifies whether congestion is concentrated on one resource or spread across the fabric. |
| VC/buffer occupancy summaries | derived from traces | Direct queue buildup metric for buffer-depth sweeps. |
| credit pressure summaries | derived from traces | Shows whether lower credits/buffers are causing stalls or queue growth. |
| per-router/per-link heatmap | derived from traces | Best visualization for localized congestion and bottlenecks. |
| saturation point | derived | Finds the offered load where bandwidth stops scaling and latency grows rapidly. |
| interference/fairness deltas | derived | Shows whether mixed traffic or multiple flows harm specific flows more than others. |

## Suggested First Sweep Matrix

Start with a narrow matrix so the tooling and plots are trustworthy:

| Family | Fixed baseline | Sweep |
| --- | --- | --- |
| AXI-MM offered load | one topology, one placement, default buffers | bandwidth `100..3200` MB/s |
| burst shape | stable bandwidth below saturation | size `16..128` bytes, length `0..15` |
| placement | one traffic profile | near/medium/far and all-to-all |
| buffers | one known-congested placement/load | `buffers_per_data_vc=1,2,4,8,16`; `buffers_per_ctrl_vc=1,2,4,8` |
| credits | same congested case | one NPS credit family at a time |
| VCs/flit size | same congested case | `vcs_per_vnet`, `ni_flit_size` |

Avoid crossing all dimensions at once. Most useful plots will come from one-variable sweeps on top of one baseline and one intentionally congested workload.
