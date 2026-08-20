# RTL endpoint-discovery test

The RTL helper discovers `xpm_nmu_mm`, `xpm_nsu_mm`, `xpm_nmu_strm`, and
`xpm_nsu_strm` instances from Verilator's hierarchy JSON.  It then generates:

- C++ signal traits and a `NocConnections` bridge wrapper;
- `<design>_noc_endpoints.json`, a stable, tool-neutral endpoint map for a
  future gem5 configuration helper.

Run the checked-in structural smoke test from the repository root:

```bash
python3 src/rtl_simulation/tests/test_endpoint_discovery.py
```

It verilates the small `EndpointDiscoverySmoke` fixture in a temporary
directory and checks all four XPM endpoint forms, including their directional
Verilator port prefixes. It also runs an AXIS loopback fixture through a
complete valid/ready transfer and backpressure check. It requires `verilator`
on `PATH`; it does not build gem5.

To generate artifacts for one in-tree or externally declared design:

```bash
python3 src/rtl_simulation/build_rtl_models.py --design <design-name>
```

For a declared RTL-to-NoC integration, use a manifest instead:

```bash
python3 src/rtl_simulation/build_rtl_models.py \
  --manifest path/to/design.rtl.json
```

Manifest paths are resolved relative to the manifest file. A manifest declares
the top module, RTL sources, include directories, and the expected XPM
instances. For every instance it also declares the NoC connection policy
(`connect_to`, `connect_loc`, and `clock_domain`). The build validates that the
RTL hierarchy and manifest agree exactly, then writes
`<design>_gem5_plan.json` next to the endpoint map.

The plan is intentionally a validated input to a generated gem5 C++ factory,
not an executable runtime configuration by itself. A compiled factory is still
needed because gem5's Verilator node wrappers are C++ template
specializations. This keeps node placement and clock/address policy explicit
rather than attempting to guess it from RTL names.

`generate_gem5_axis_node.py` implements the first factory shape: one AXIS
`xpm_nsu_strm` ingress and one AXIS `xpm_nmu_strm` egress. It deliberately
rejects AXI-MM and multi-port plans instead of guessing their ordering or
connection policy. After building a compatible manifest, generate a stable
gem5 SimObject/C++ wrapper and rebuild with external RTL enabled:

```bash
python3 src/rtl_simulation/generate_gem5_axis_node.py \
  src/rtl_simulation/build/<design>/<design>_noc_endpoints.json \
  src/rtl_simulation/build/<design>/<design>_gem5_plan.json \
  --class-name <Gem5NodeClass> \
  --output-dir src/noc/endpoints/rtl/generated

scons build/NULL/gem5.opt BUILD_EXTERNAL_RTL=1 -j$(nproc)
```

The generator matches the named Verilator prefix produced by
`build_rtl_models.py`, and the generated files are source inputs: keep the
manifest, endpoint map, and generated wrapper in sync whenever the RTL port
hierarchy changes. `BUILD_EXTERNAL_RTL=1` registers only legacy hand-written
RTL nodes whose independently generated models are present; it always
registers valid manifest-generated nodes. This makes a focused manifest build
independent of unrelated legacy SmartNIC models.

## AXI-MM V1 reference regression

`hw/designs/AximmMemorySmoke/` is the checked-in AXI-MM reference fixture.
It contains one `xpm_nsu_mm` NoC destination connected to a one-beat,
memory-like RTL slave. Build the Verilated model, then build gem5 with the
external RTL integration enabled:

```bash
python3 src/rtl_simulation/build_rtl_models.py \
  --manifest src/rtl_simulation/hw/designs/AximmMemorySmoke/AximmMemorySmoke.rtl.json

scons build/NULL/gem5.opt BUILD_EXTERNAL_RTL=1 -j$(nproc)
```

For another design with the same V1 contract, generate its typed wrapper
before the gem5 build. Its manifest must include a `gem5_wrapper` object with
the Verilator root clock/reset member names and the AXI-MM data, ID, and
address widths. This makes those compatibility settings reviewable inputs,
rather than generator command-line defaults.

```bash
python3 src/rtl_simulation/generate_gem5_aximm_node.py \
  src/rtl_simulation/build/<design>/<design>_noc_endpoints.json \
  src/rtl_simulation/build/<design>/<design>_gem5_plan.json \
  --class-name <Gem5NodeClass> \
  --output-dir src/noc/endpoints/rtl/generated
```

Run the deterministic NoC regression with:

```bash
build/NULL/gem5.opt \
  --outdir=/tmp/noc-aximm-rtl-memory-smoke \
  src/noc/testing/generic/aximm_rtl_memory_smoke.py
```

A passing run reports four completed 64-byte writes and four completed
64-byte reads, then exits because reads and writes completed. The test covers
the documented AXI-MM V1 behavior: a 512-bit, one-beat AW-before-W write and
the corresponding read response through the existing NoC AXI-MM layer.
For scope and limitations, see `docs/NOC_RTL_AXIMM_V1.md`.

Run the portable wrapper-contract checks independently with:

```bash
python3 -m unittest -v src/rtl_simulation/tests/test_aximm_wrapper_v1.py
```

They verify generator output and clear rejection of unsupported AXI-MM master
plans. When Verilator is available, they also verify the reference fixture's
partial-WSTRB update and exact 512-bit readback data.

Verilator model outputs are intentionally kept under
`src/rtl_simulation/build/` (or the `--build-dir` supplied by the caller) and
are not source-controlled. In contrast, the small generated gem5 wrapper
under `src/noc/endpoints/rtl/generated/` is a build input and should be
reviewed and committed with its manifest.
