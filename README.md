# Naviq NoC Simulator

Naviq is a public gem5 fork with a cycle-level AMD NoC extension. It supports
AXIS and AXI-MM traffic, BRAM, DDR, HBM, CPU, SmartNIC, and optional RTL
experiments. `main` is the supported public branch; integration work is
validated through pull requests before it is merged.

Project owner and maintainer: **Professor Deming Chen**, University of
Illinois Urbana-Champaign.

Start with the [NoC user guide](docs/NOC_USER_GUIDE.md),
[repository layout](docs/NOC_LAYOUT.md), and
[test guide](src/noc/testing/README.md). The
[experiment launcher](noc_testing/experiments/README.md) lists reproducible
campaigns and their external requirements.

## Quick start

Create an isolated Python environment for the NoC experiment and analysis
tools:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Build the gem5 variant for your workload:

| Variant | ISA | Use case |
| --- | --- | --- |
| `NULL` | None | NoC-only traffic-generator simulations and portable tests |
| `ARM` | ARM | ARM CPU compatibility scenarios |
| `RISCV` | RISC-V | RISC-V CPU compatibility scenarios |
| `X86` | X86 | X86 CPU, DDR, and SmartNIC scenarios |

```bash
scons build/NULL/gem5.opt -j$(nproc)
```

Replace `NULL` with `ARM`, `RISCV`, or `X86` when needed. Replace `.opt` with
`.debug` for a debug build with full assertions.

## Running and testing

Run a small NoC-only scenario from the repository root:

```bash
./build/NULL/gem5.opt src/noc/testing/generic/aximm_1_to_1_close_smoke.py
```

Run the portable quick gate and the HBM gate from `tests/`:

```bash
cd tests
./main.py run --skip-build --length=quick --isa=NULL --variant=opt gem5/noc
./main.py run --skip-build --isa=NULL --variant=opt \
  --exclude-tags '.*' --include-tags noc-hbm gem5/noc
```

CPU setup commands are maintained as compatibility paths. Use the
[CPU NoC guide](src/noc/cpu/cpu_noc_guide.md) rather than copying unvalidated
topology paths from old notes.

## NoC documentation

- [NoC user guide](docs/NOC_USER_GUIDE.md)
- [NoC architecture](docs/NOC_ARCHITECTURE.md)
- [NoC source guide](src/noc/README.md)
- [NoC testing and release gates](src/noc/testing/README.md)
- [Reproducible experiments](noc_testing/experiments/README.md)
- [Experiment guide](docs/NOC_EXPERIMENTS.md)
- [Repository layout](docs/NOC_LAYOUT.md)
- [Artifact policy](docs/NOC_ARTIFACT_POLICY.md)
- [Archive index](archive/noc/INDEX.md)
- [Maintenance backlog](docs/NOC_MAINTENANCE_BACKLOG.md)
- [Release status and limitations](docs/NOC_RELEASE_NOTES.md)
- [Publication checklist](docs/NOC_PUBLICATION.md)

## Upstream gem5

Naviq retains gem5's source and licensing. For general gem5 build,
configuration, resources, and contribution guidance, see the
[gem5 documentation](https://www.gem5.org/documentation/) and the
[upstream repository](https://github.com/gem5/gem5). For AMD NoC background,
see the [AMD NoC documentation](https://docs.amd.com/r/en-US/pg313-network-on-chip/).
