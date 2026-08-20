#!/usr/bin/env python3
"""Generate a V1 gem5 AXI-MM RTL slave wrapper from a validated plan.

V1 intentionally supports one ``xpm_nsu_mm`` endpoint.  The endpoint is a
NoC destination that exposes an AXI master port to the Verilated design.  The
generated node reuses gem5's existing AXI-MM NoC implementation; it only
instantiates the typed RTL bridge.  Placement, clock-domain labels, and
address policy remain in the manifest and topology JSON files.
"""

import argparse
import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REQUIRED_WRAPPER_FIELDS = (
    "clock_signal",
    "reset_signal",
    "data_width",
    "id_width",
    "addr_width",
)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def trait_name(endpoint):
    """Return the generated AxiPortBinding trait name for one XPM endpoint."""
    return "Axi_{}Traits".format(endpoint["verilator_path"])


def header(class_name, top, endpoint, clock_signal, reset_signal):
    return f'''#pragma once

#include "{top}.h"
#include "{top}___024root.h"
#include "{top}_verilator_mappings.h"
#include "noc/endpoints/rtl/AximmRtlSlaveNode.hh"
#include "params/{class_name}.hh"

namespace gem5::noc
{{

struct {class_name}WrapperTraits
{{
    using AxiTraits = {top}_verilator::{trait_name(endpoint)};

    static auto &clock({top} &dut) {{ return dut.rootp->{clock_signal}; }}
    static auto &resetn({top} &dut) {{ return dut.rootp->{reset_signal}; }}
}};

class {class_name} : public AximmRtlSlaveNode<
    {top}, {class_name}Params, {class_name}WrapperTraits>
{{
  public:
    using Params = {class_name}Params;

    explicit {class_name}(const Params &p)
        : AximmRtlSlaveNode(p, "{class_name}")
    {{}}
}};

}} // namespace gem5::noc
'''


def simobject(class_name, data_width, id_width, addr_width):
    return f'''from m5.params import *
from m5.proxy import *
from m5.objects import NocNode


class {class_name}(NocNode):
    type = "{class_name}"
    cxx_header = "noc/endpoints/rtl/generated/{class_name}.hh"
    cxx_class = "gem5::noc::{class_name}"

    noc_system = Param.NocSystem(Parent.any, "")
    data_width = Param.UInt32({data_width}, "AXI-MM data width in bits")
    id_width = Param.UInt32({id_width}, "AXI-MM ID width in bits")
    addr_width = Param.UInt32({addr_width}, "AXI-MM address width in bits")
    reset_cycles = Param.UInt32(4, "RTL reset cycles")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint_map")
    parser.add_argument("gem5_plan")
    parser.add_argument("--class-name", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    try:
        endpoint_map = load(args.endpoint_map)
        plan = load(args.gem5_plan)
    except (OSError, json.JSONDecodeError) as error:
        parser.error("could not read endpoint map or gem5 plan: {}".format(error))
    if endpoint_map.get("top_module") != plan.get("top_module"):
        parser.error("endpoint map and plan top modules differ")
    top = endpoint_map.get("top_module")
    if not isinstance(top, str) or not IDENTIFIER.fullmatch(top):
        parser.error("endpoint map top_module must be a C++ identifier")
    if not IDENTIFIER.fullmatch(args.class_name):
        parser.error("--class-name must be a C++ identifier")

    nodes = plan.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 1:
        parser.error(
            "AXI-MM V1 requires a plan with exactly one xpm_nsu_mm endpoint"
        )
    endpoint = nodes[0].get("endpoint", {})
    if (
        endpoint.get("protocol") != "aximm"
        or endpoint.get("role") != "nsu"
        or endpoint.get("module_type") != "xpm_nsu_mm"
        or endpoint.get("signal_prefix") != "m_axi_"
        or not isinstance(endpoint.get("verilator_path"), str)
    ):
        parser.error(
            "AXI-MM V1 supports one xpm_nsu_mm endpoint with m_axi_ signals; "
            "xpm_nmu_mm and mixed/multi-endpoint plans need another wrapper"
        )
    discovered = {
        item.get("id"): item for item in endpoint_map.get("endpoints", [])
    }
    if discovered.get(endpoint.get("id")) != endpoint:
        parser.error("the plan endpoint does not exactly match the endpoint map")

    wrapper = plan.get("gem5_wrapper")
    if not isinstance(wrapper, dict):
        parser.error("plan is missing the gem5_wrapper object from its manifest")
    missing = [field for field in REQUIRED_WRAPPER_FIELDS if field not in wrapper]
    if missing:
        parser.error(
            "AXI-MM V1 requires gem5_wrapper fields: {}".format(
                ", ".join(missing)
            )
        )
    for field in ("clock_signal", "reset_signal"):
        if not isinstance(wrapper[field], str) or not IDENTIFIER.fullmatch(
            wrapper[field]
        ):
            parser.error("gem5_wrapper.{} must be a C++ member name".format(field))
    data_width = wrapper["data_width"]
    id_width = wrapper["id_width"]
    addr_width = wrapper["addr_width"]
    if (
        not isinstance(data_width, int)
        or isinstance(data_width, bool)
        or not 32 <= data_width <= 512
        or data_width % 8
    ):
        parser.error("gem5_wrapper.data_width must be a multiple of 8 in [32, 512]")
    if (
        not isinstance(id_width, int)
        or isinstance(id_width, bool)
        or not 1 <= id_width <= 32
    ):
        parser.error("gem5_wrapper.id_width must be in [1, 32]")
    if (
        not isinstance(addr_width, int)
        or isinstance(addr_width, bool)
        or not 1 <= addr_width <= 64
    ):
        parser.error("gem5_wrapper.addr_width must be in [1, 64]")

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / (args.class_name + ".hh")).write_text(
        header(
            args.class_name,
            top,
            endpoint,
            wrapper["clock_signal"],
            wrapper["reset_signal"],
        ),
        encoding="utf-8",
    )
    (output / (args.class_name + ".py")).write_text(
        simobject(args.class_name, data_width, id_width, addr_width),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
