from m5.params import *
from m5.proxy import *
from m5.SimObject import SimObject


class NocProbe(SimObject):
    """NoC debug probe (snooper / comparator); hooks wired via noc_probe on targets."""

    type = "NocProbe"
    cxx_header = "noc/debug/NocProbe.hh"
    cxx_class = "gem5::noc::NocProbe"

    probe_id = Param.String(
        "",
        "User-provided probe identifier from node config JSON. For comparator "
        "latency when hook_id_1 is a flit/msg hook, include exactly one of: "
        "'axis_payload' (use axisPayload.debugIds) or 'flit' (use the flit/msg "
        "debug id). Matching is case-insensitive.",
    )

    noc_system = Param.NocSystem(NULL, "Owning NoC system (system.noc)")

    probe_mode = Param.String(
        "snooper",
        "Operating mode: snooper (hook points 0–1) or comparator (hook points 0 and 1)",
    )

    comparator_op = Param.String(
        "latency",
        "When probe_mode is comparator: latency (cycles hook0→hook1), or "
        "path_match (stats on hook0 observations vs hook1; prints "
        "never_reached_hook1 at simulation end).",
    )

    hook_id_0 = Param.String(
        "",
        "Hook id for hook point 0 (e.g. noc_if.node.to_cdc); required when enabled",
    )

    hook_id_1 = Param.String(
        "",
        "Hook id for hook point 1; optional for snooper, required for comparator",
    )

    enabled = Param.Bool(
        True,
        "If false, skip hook validation, exit callbacks, and all onHookEvent work. "
        "Node JSON may set enabled to 0 or 1.",
    )

    path_match_trace = Param.Bool(
        False,
        "If true and comparator_op is path_match, print each hook0 assign id and "
        "each hook1 pop (match); also hook1 ids not in pending (stray). "
        "JSON: path_match_trace 0 or 1.",
    )

    # --- Snooper mode configuration ---
    snoop_fields = VectorParam.String(
        [],
        "Snooper field IDs to print (ordered). Parsed from hook_point_0.fields in node_config JSON.",
    )
    snoop_print_cycles = Param.UInt64(
        0,
        "Snooper print period in NoC cycles (0 disables periodic printing). Parsed from hook_point_0.print_cycles.",
    )
