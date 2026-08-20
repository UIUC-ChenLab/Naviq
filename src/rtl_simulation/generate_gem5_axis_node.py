#!/usr/bin/env python3
"""Generate a gem5 AxisRtlStreamNode specialization from a validated plan.

Version 1 deliberately supports one AXIS NSU ingress and one AXIS NMU egress.
That is the smallest complete generated gem5 wrapper shape; AXI-MM and
multi-port generation are rejected rather than silently miswired.
"""
import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text())


def signal_prefix(endpoint):
    return endpoint["verilator_path"] + "__DOT__" + endpoint["signal_prefix"]


def traits(name, top, ingress, egress):
    # build_rtl_models.py passes ``--prefix <design>`` to Verilator, so the
    # generated C++ model header and class are both named after ``top`` (not
    # Verilator's default V<top> spelling).  Keeping this contract here makes
    # the generated node compile against the exact model build that produced
    # its endpoint map.
    def refs(prefix):
        return "\n".join(
            "    auto& {0}_ref({1}& dut) const {{ return dut.rootp->{2}{0}; }}".format(
                field, top, prefix
            )
            for field in ("tdata", "tkeep", "tuser", "tid", "tdest", "tlast", "tvalid", "tready")
        )
    return f'''#pragma once
#include "{top}.h"
#include "{top}___024root.h"
#include "noc/endpoints/rtl/AxisRtlStreamNode.hh"
#include "params/{name}.hh"

namespace gem5::noc {{
struct {name}IngressTraits {{
{refs(signal_prefix(ingress))}
}};
struct {name}EgressTraits {{
{refs(signal_prefix(egress))}
}};
struct {name}WrapperTraits {{
    using IngressTraits = {name}IngressTraits;
    using EgressTraits = {name}EgressTraits;
    static auto& clock({top}& dut) {{ return dut.rootp->clk; }}
    static auto& resetn({top}& dut) {{ return dut.rootp->resetn; }}
    static auto& egressTready({top}& dut) {{ return dut.rootp->{signal_prefix(egress)}tready; }}
    static void driveSideInputs({top}&) {{}}
    static void driveSideInputs({top}& dut, uint64_t) {{ driveSideInputs(dut); }}
    static void driveIdleSideInputs({top}& dut) {{ driveSideInputs(dut); }}
}};
class {name} : public AxisRtlStreamNode<{top}, {name}Params, {name}WrapperTraits, 1> {{
  public:
    using Params = {name}Params;
    explicit {name}(const Params& p) : AxisRtlStreamNode(p, "{name}") {{}}
}};
}} // namespace gem5::noc
'''


def simobject(name):
    return f'''from m5.params import *
from m5.proxy import *
from m5.objects import NocNode

class {name}(NocNode):
    type = "{name}"
    cxx_header = "noc/endpoints/rtl/generated/{name}.hh"
    cxx_class = "gem5::noc::{name}"
    noc_system = Param.NocSystem(Parent.any, "")
    data_width = Param.UInt32(512, "AXIS TDATA width")
    id_width = Param.UInt32(16, "AXIS TID width")
    dest_width = Param.UInt32(12, "AXIS TDEST width")
    user_width = Param.UInt32(1, "AXIS TUSER width")
    expected_packets = Param.UInt32(0, "Packets expected to drain")
    reset_cycles = Param.UInt32(4, "RTL reset cycles")
    metrics_output_path = Param.String("", "Optional metrics JSON")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint_map")
    parser.add_argument("gem5_plan")
    parser.add_argument("--class-name", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    endpoint_map, plan = load(args.endpoint_map), load(args.gem5_plan)
    axes = [node["endpoint"] for node in plan["nodes"] if node["endpoint"]["protocol"] == "axis"]
    ingress = [e for e in axes if e["role"] == "nsu"]
    egress = [e for e in axes if e["role"] == "nmu"]
    if len(ingress) != 1 or len(egress) != 1 or len(axes) != 2:
        parser.error("v1 requires exactly one AXIS NSU ingress and one AXIS NMU egress")
    if endpoint_map["top_module"] != plan["top_module"]:
        parser.error("endpoint map and plan top modules differ")
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / (args.class_name + ".hh")).write_text(
        traits(args.class_name, endpoint_map["top_module"], ingress[0], egress[0])
    )
    (output / (args.class_name + ".py")).write_text(simobject(args.class_name))


if __name__ == "__main__":
    main()
