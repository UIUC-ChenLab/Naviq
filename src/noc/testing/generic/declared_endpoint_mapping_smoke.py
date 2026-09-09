"""Instantiate declared idle PL endpoints without inventing traffic routes.

Run with gem5.fast and --placement baseline or adverse. Checks both placement
documents, then instantiates the selected actual 44-port RTL/CPU setup and
clocks one PE cycle. No control program or packet workload is run.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import m5
from m5.objects import Root

REPO = Path(__file__).resolve().parents[4]
for directory in ("src/noc/setup", "src/noc/setup/include", "src/noc/testing", "configs"):
    sys.path.insert(0, str(REPO / directory))
from noc_config_funcs import get_address_map, get_parser
from noc_setup_config import build_system_from_setup
from setup_schema import load_setup

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--placement", choices=("baseline", "adverse"), default="baseline")
args = parser.parse_args()

out = Path(m5.options.outdir).resolve()
out.mkdir(parents=True, exist_ok=True)


def parse(name, nts, ncr):
    a, b = out / f"{name}.nts", out / f"{name}.ncr"
    a.write_text(json.dumps(nts))
    b.write_text(json.dumps(ncr))
    return get_address_map(str(a), str(b))


logical = ["S00_AXIS_nmu", "S01_AXIS_nmu", "M00_AXIS_nsu", "M01_AXIS_nsu"]
physical = ["NOC_NMU512_X0Y0", "NOC_NMU512_X1Y0", "NOC_NSU512_X0Y1", "NOC_NSU512_X1Y1"]
nts = dict(LogicalInstances=[dict(Name="axis_noc_0/inst/" + name,
    CompType="PL_NMU" if name.startswith("S") else "PL_NSU", Protocol="AXI_STRM",
    IsMaster=name.startswith("S"), AxiDataWidth=512, SysAddresses=[])
    for name in logical], Paths=[])
ncr = dict(Components=[dict(Name=p, TrafficLInst="axis_noc_0/inst/" + n)
    for n, p in zip(logical, physical)], Paths=[])
topology = parse("declared_without_routes", nts, ncr)
assert len(topology.endpoints) == 4
for name, site in zip(logical, physical):
    assert topology.get_endpoint_by_physical(site).logical_name == name
assert not any(topology.axis_nmu_to_dest_names.values()), "Declaring an idle port must not invent an AXIS route"

# Legacy documents without Components still resolve their routed endpoints.
legacy = dict(Paths=[dict(From="axis_noc_0/inst/S00_AXIS_nmu", To="axis_noc_0/inst/M00_AXIS_nsu",
    Nets=[dict(PhyInstanceStart=physical[0], PhyInstanceEnd=physical[2], CommType="WRITE")])])
topology = parse("legacy_path_mapping", nts, legacy)
assert topology.get_endpoint_by_physical(physical[0]).logical_name == logical[0]
assert topology.get_endpoint_by_physical(physical[2]).logical_name == logical[2]

study = REPO / "src/noc/testing/smartnic/latency_sensitivity_nat_mc"
connections = json.loads((study / "connections.json").read_text())
idle = {f"overloaded_nat.u_rx_packet_{direction}_{lane}_{suffix}"
        for direction, suffix in (("in", "nsu"), ("out", "nmu")) for lane in (0, 1)}
assert all(link["from"] not in idle and link["to"] not in idle for link in connections["connections"])
for placement in ("baseline", "adverse"):
    a, b = out / f"{placement}.nts", out / f"{placement}.ncr"
    command = ["python3", str(REPO / "noc_testing/tools/topology/generate_ncr.py"),
        "--connections", str(study / "connections.json"),
        "--placement", str(study / f"{placement}.place.json"),
        "--nts", str(a), "--ncr", str(b), "--router", "shortest_path"]
    with (out / f"{placement}_generation.log").open("w") as log:
        subprocess.run(command, cwd=REPO, stdout=log, stderr=subprocess.STDOUT, check=True)
    topology = get_address_map(str(a), str(b))
    sites = json.loads((study / f"{placement}.place.json").read_text())["placements"]
    assert len(topology.endpoints) == len(sites) == 44
    for endpoint, site in sites.items():
        assert topology.get_endpoint_by_physical(site) is not None, (placement, endpoint, site)
    routes = json.loads(b.read_text())["Paths"]
    components = json.loads(b.read_text())["Components"]
    attachments = {c["Name"]: c["AttachedRouter"] for c in components if c.get("TrafficLInst")}
    assert set(attachments) == set(sites.values())
    routed_sites = {net[key] for route in routes for net in route["Nets"]
                    for key in ("PhyInstanceStart", "PhyInstanceEnd")}
    for endpoint in idle:
        assert sites[endpoint] not in routed_sites, "Idle NAT RX acquired a fictitious route"
    print(f"PASS {placement}: all 44 declarations map; four idle NAT RX ports remain unrouted")

# Instantiate the actual study, including the unused NAT RX interfaces. This
# catches the external-link node allocation failure that parser checks miss.
sys.path.insert(0, str(study))
from run import configure_cpu

sys.argv = [sys.argv[0], "--sys-clock", "400MHz", "--noc-clock", "1GHz",
            "--sim-cycles", "1000000000"]
options = get_parser()
a, b = out / f"{args.placement}.nts", out / f"{args.placement}.ncr"
topology = get_address_map(str(a), str(b))
setup = load_setup(str(study / "connections.json"),
                   str(study / f"{args.placement}.place.json"), [])
system = build_system_from_setup(options, setup, topology, str(b))
nodes = {c.component_id: n for c, n in zip(setup.components, system.cpu)}
physical_names = {}
index = 0
for component in setup.components:
    for port in component.ports:
        physical_names[port.endpoint] = topology.get_endpoint_by_physical(
            setup.placement_for(port.endpoint)).logical_name
        netif = system.noc.network.netifs[index]
        if port.protocol == "aximm" and port.role == "slave":
            netif.data_width = 32
        if port.protocol == "axis" and port.role == "slave":
            netif.axis_tid_width = 6
        index += 1
rtl = REPO / "src/rtl_simulation/hw/designs/AdaptNICLatencyNatMulticast"
instances = json.loads((rtl / "instances_implicit.json").read_text())
instances.append(json.loads((rtl / "host_fabric.instance.json").read_text()))
for instance in instances:
    name = instance["name"]
    nodes[name].port_endpoint_names = [
        name + "." + e["name"] if e.get("transport") == "direct"
        else physical_names[name + "." + e["name"]]
        for e in instance["endpoints"]]
    nodes[name].clockDomains = [400] * len(instance["endpoints"])
configure_cpu(system, nodes["cpu_mmio"], study / "control_x86", out)
network = system.noc.network
assert len(network.netifs) == len(network.ext_links) == len(topology.endpoints) == 44
controllers = list(system.noc.tile_controllers)
assert sorted(controllers.index(link.ext_node) for link in network.ext_links) == list(range(44))
rules = json.loads(str(network.custom_routing_table_json))
idle_ids = {index for index, endpoint in enumerate(physical_names) if endpoint in idle}
assert len(idle_ids) == 4
idle_links = [link for link in network.ext_links if controllers.index(link.ext_node) in idle_ids]
assert not any(rule[0] in [int(link.link_id) for link in idle_links] for rule in rules)
assert not any(rule[1] in idle_ids or rule[2] in idle_ids for rule in rules)
root = Root(full_system=False, system=system)
m5.ticks.setGlobalFrequency("1ps")
m5.instantiate()
event = m5.simulate(2500)
assert event.getCause() == "simulate() limit reached"
assert not network.hasOutstandingTransactions()
result = dict(placement=args.placement, endpoints=44, external_links=44,
              idle_endpoints=4, idle_traffic_routes=0, tick=int(m5.curTick()), **{"pass": True})
(out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("DECLARED_ENDPOINT_MAPPING_PASS", json.dumps(result))
