# NoC User Guide

## Supported public configuration

The NoC extension is released as part of this gem5 fork. The portable entry
point is a NULL-ISA gem5 build with the schema-driven NoC setup script:

```sh
scons build/NULL/gem5.opt -j$(nproc)
./build/NULL/gem5.opt src/noc/setup/noc_config.py \
    --noc-topology=src/noc/topology/topologies/<topology-bundle>
```

Use the checked-in smoke scenarios and experiment manifests instead of copying
ad-hoc command lines. The test guide documents the stable test tiers and the
experiment guide documents campaign-specific prerequisites.

## Protocol support

- AXIS packet traffic is covered by deterministic packetization,
  depacketization, FIFO, sideband, and MTU boundary regressions.
- AXI-MM supports the tested AW-before-W write-channel subset, bounded
  interleaved read/write traffic, multiple AXI IDs for read responses, and
  WSTRB preservation through 256-byte NPP packetization.
- W-before-AW is not a supported AXI-MM sequence in this release. The model
  does not retain W data before a matching address request is available.
- AXI-MM W-channel admission is modeled with the current buffer occupancy;
  exact next-beat admission at the 512-byte limit is future work.

## Tests

Run the portable release checks from a built checkout:

```sh
cd tests
./main.py run --skip-build --length=quick --isa=NULL --variant=opt gem5/noc
./main.py run --skip-build --isa=NULL --variant=opt \
  --exclude-tags '.*' --include-tags noc-hbm gem5/noc
cd ..
src/noc/testing/run_noc_gtests.sh
cd tests
./main.py run --skip-build --exclude-tags '.*' --include-tags noc-vivado \
    --isa=NULL --variant=opt gem5/noc
```

The `noc-hbm` TestLib suite is portable and validates the released HBM-NMU
path. The Vivado acceptance check compares against a pinned reference and does
not launch Vivado. CPU, DDR, full HBM campaign, Vivado, and external-RTL runs
may require additional documented tools; Vivado and external RTL require their
licensed environment.

## Style checks

Follow the surrounding gem5 C++ and Python style. The repository's existing
pre-commit configuration is the formatting/lint entry point:

```sh
pre-commit run --all-files
```

Do not apply a repository-wide formatter to NoC code as a cleanup shortcut.
Keep style-only changes focused and separate from behavior changes.
