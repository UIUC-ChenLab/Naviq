# Naviq Public Release Plan

This checklist defines the remaining work for a reproducible public release.
The public repository begins with a clean history containing only the selected
release source tree.

## Completed

- [x] Organize the NoC implementation, tests, topology fixtures, and experiment
  runners into documented public directories.
- [x] Vendor the required SystemVerilogAXI source dependency and its licenses.
- [x] Add portable quick TestLib coverage, focused C++ tests, and pinned Vivado
  acceptance data.
- [x] Document supported behavior, known limitations, and artifact policy.
- [x] Identify Professor Deming Chen as project owner and maintainer.
- [x] Identify University of Illinois Urbana-Champaign as copyright holder.

## Before the first public tag

- [ ] Add the approved paper/publication citation or explicitly state that one
  is not yet available.
- [ ] Ensure public CI runs on runner infrastructure available to this
  repository.
- [ ] Run formatting and secret-scanning checks against the exact committed
  release tree.
- [ ] Build and run the portable NoC release gate from a clean clone.
- [ ] Record the release commit, vendored dependency revision, and test results
  in `docs/NOC_RELEASE_NOTES.md`.

## Release gates

```bash
scons --no-compress-debug build/NULL/gem5.opt -j$(nproc)

cd tests
./main.py run --skip-build --length=quick --isa=NULL --variant=opt gem5/noc
cd ..

src/noc/testing/run_noc_gtests.sh
python3 noc_testing/experiments/run_experiment.py --dry-run-all
```

The checked-in Vivado acceptance data provides a portable comparison. Full
Vivado reproduction additionally requires the documented external installation
and licenses.

## Stable-release criteria

- `main` builds from a clean clone.
- The documented release gates pass.
- Released capabilities and limitations match the implementation.
- Required licenses and third-party attribution remain present.
- Reproducible experiments identify all external tool, license, and hardware
  requirements.
