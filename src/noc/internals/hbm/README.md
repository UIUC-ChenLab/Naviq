# HBM implementation status

This directory contains HBM-specific internal declarations.  The HBM arbiter
is still compiled through `src/noc/hbm/HBMArbiter.cc`, which includes its header
from this directory.

HBM master-unit support is a first-release feature. The supported `HBM_NMU`
topology endpoint uses the maintained `mmNocMasterUnit` implementation, with
the HBM controller and arbiter providing its memory-side behavior. The HBM
TestLib scenarios under `src/noc/testing/hbm/` validate that supported path.

There is intentionally no separate `HBMNocMasterUnit` SimObject. New HBM
master behavior belongs in `mmNocMasterUnit` and must be covered by the
`noc-hbm` TestLib suite.
