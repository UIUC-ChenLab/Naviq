# NCRB/NIDB internal ingress buffering

Each NCRB/NIDB incoming physical link has **eight internal flit slots in
total**, shared by all of that input's virtual channels. The reverse direction
uses its own pool at the receiving router. This bounds the internal pipeline
storage; the existing input-VC buffers and their advertised credits remain
separate. With the study's 128-bit NoC links, eight flits hold 128 bytes.

`NocRouter::InternalIngressCapacity` defines the bound. Per-VC FIFOs retain
ordering while a shared per-input count enforces capacity. A round-robin scan
admits at most one flit per input per NoC cycle. Admission reserves a free slot
before removing an input flit or returning its upstream credit. When all eight
slots are occupied, the router leaves the flit in its input VC and withholds
the credit, propagating backpressure. Switch allocation reclaims the slot;
it does not return a second upstream credit. A slot freed later in the cycle
is available on the next cycle.

Router latency and output-VC packet locking are unchanged. Multiple wakeups at
the same tick cannot admit multiple flits from one link. A flit arriving after
the current tick's admission is retried on the next cycle.

The existing `--nps-queue-trace 1` CSV now includes `internal_ingress` rows for
each occupied VC. Sum these rows by `(tick, router_id, inport)` to obtain the
shared pool occupancy; it must never exceed eight. There is no duplicate
aggregate row. Existing heatmaps include these rows, and
`noc_testing/topology_analysis.py` reports internal storage separately.
Aggregate NPS occupancy also includes each internal pool once.

Per-input statistics are available without enabling the CSV trace:

- `internal_ingress_accepted` and `internal_ingress_drained`: admitted and
  allocated flits. They match after a run starts empty and completely drains.
- `internal_ingress_blocked_cycles`: NoC cycles when a ready input could not
  enter a full internal pool.
- `internal_ingress_peak`: maximum simultaneous internal occupancy, summed
  over VCs for that incoming link.
- `internal_ingress_average`: time-average occupancy over the statistics
  interval, including idle time unless statistics are reset for a window.

Network outstanding checks and functional accesses include the internal
buffers. Checkpoints save the internal flits and admission arbitration state.
Old NCRB/NIDB checkpoints lack this state and cannot restore this model safely.

From the Naviq directory, run the deterministic backpressure regression with:

```sh
python3 src/noc/testing/generic/axis_internal_ingress_backpressure_smoke.py \
  --gem5 build/X86/gem5.fast --outdir m5out/internal-ingress-backpressure
python3 -m unittest discover -s noc_testing -p test_topology_analysis.py
```

The simulation regression exercises NCRB and NIDB links in both directions,
two VCs sharing each pool, a long deterministic sink hold, stopped upstream
sources, exact packet recovery, and complete draining. Its trace and statistics
checks require the shared peak to reach exactly eight without exceeding it.
It also retains the existing same-VC passthrough arbitration regression.

# Output token reloads

For token-arbitrated NPS outputs, a reload replaces every input/VC counter for
that output with its configured initial budget, including idle, credit-blocked,
and packet-lock-blocked inputs. Other outputs keep their existing counters.
The current model initializes every budget to 16; it does not yet import NPI
QoS weights. Reload eligibility still uses the filtered request set: at least
one requester has zero tokens and none has positive tokens. Packet locks,
credit checks, and LRU grant selection still apply after the reload.

A focused regression uses the real allocator and native arbitration trace:

```sh
NOC_CSV_OUTPUT_DIR=m5out/token-reload/noc_csv \
NOC_GRAPH_OUTPUT_DIR=m5out/token-reload/graphs \
build/X86/gem5.fast --outdir=m5out/token-reload \
  src/noc/testing/generic/axis_shared_nsu_interleaving_smoke.py \
  --shared-vc --packets-per-source 128 --frame-sizes 65,140,176,192 \
  --frame-destinations 0 \
  --sink-ready-percent 100 --nps-queue-trace 1
python3 src/noc/testing/generic/verify_output_token_reload.py m5out/token-reload
```

The scenario checks exact packet bytes and complete drainage. The trace checker
requires a refill while another input is blocked by a packet lock, checks the
waiting input's restored budget, and verifies that its waiting flit is granted
after the owner's tail. Omitting `--shared-vc` and using a fresh output directory
with checker option `--coverage cross-vc` also checks refresh across VCs.

The token cases use one TDEST while retaining both TIDs. With mixed TDESTs,
legal AXIS interleaving can currently trip `NocInterface::ProtocolChecker`'s
single channel-wide `packetDest` state. The focused tests keep that checker
enabled and still reconstruct and check every packet independently by TID.
The shared-NSU test's default mixed-destination behavior is unchanged.
