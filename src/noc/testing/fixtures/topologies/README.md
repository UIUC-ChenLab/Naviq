# NoC Smoke Topology Fixtures

These fixtures are the current, checked-in topology bundles used by the public
generic TestLib smokes. Each bundle pins its connection and placement inputs
from `noc_testing/topology_jsons/` together with the generated `.nts` and
`.ncr` descriptions. Keeping all four files together avoids a Vivado or
topology-generation dependency in the fast release gate.

The HBM smoke fixtures use the same rule. The shared-controller fixture owns a
complete bundle under this directory; the other HBM fixtures pair their pinned
`.nts`/`.ncr` files here with maintained connection and placement inputs under
`noc_testing/topology_jsons/hbm/`.

The SmartNIC rate-limiter fixture is likewise complete and self-contained under
`smartnic/`. Do not use archived topology inputs under `archive/noc/topologies/`
for a release smoke.

Regenerate a fixture only after intentionally changing its topology source.
For example, from the repository root, regenerate the AXI-MM 2-to-2 fixture
with:

```sh
python3 noc_testing/tools/topology/generate_ncr.py \
  --connections noc_testing/topology_jsons/multi_endpoint/2to2_aximm.conn.json \
  --placement noc_testing/topology_jsons/multi_endpoint/2to2_aximm.place.json \
  --ncr src/noc/testing/fixtures/topologies/2to2_aximm/2to2_aximm.ncr \
  --nts src/noc/testing/fixtures/topologies/2to2_aximm/2to2_aximm.nts
```

Then inspect the diff and run the fixture, AXI-MM, and AXIS TestLib groups:

```sh
cd tests
./main.py run --exclude-tags '.*' --include-tags noc-fixture gem5/noc
./main.py run --exclude-tags '.*' --include-tags 'noc-aximm|noc-axis' \
  --isa=NULL --variant=opt gem5/noc
```
