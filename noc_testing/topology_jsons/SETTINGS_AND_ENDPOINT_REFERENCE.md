# Settings And Endpoint Reference

This file is the detailed companion to `CONN_AND_PLACE_GUIDE.md`. It explains what can go where in `*.conn.json` and `*.place.json` files, with special focus on component params, port config, clock domains, DDR, HBM, and endpoint-specific rules.

Examples:

- Minimal: `examples/simple_aximm_1to1.conn.json` and `examples/simple_aximm_1to1.place.json`
- Detailed: `examples/detailed_mixed_clocked.conn.json` and `examples/detailed_mixed_clocked.place.json`

## Where Settings Can Live

There are four useful settings layers.

## Top-Level Settings

Top-level settings are global to the generated topology:

```json
{
  "ddr_settings": {},
  "hbm_settings": {}
}
```

The schema collects top-level objects whose names end in `_settings`. Current practical settings are `ddr_settings` and `hbm_settings`.

Top-level settings are not SimObject constructor parameters. They guide topology generation, `.nts` generation, memory-controller setup, or runtime memory configuration.

## Component Params

Component params live at:

```json
components.<component_id>.params
```

They are copied into the runtime component constructor. They should match parameters accepted by the component's gem5 SimObject class.

Examples:

```json
"tg_0": {
  "node_type": "AxiRandomTrafficGenerator",
  "params": {
    "max_write_commands": 16,
    "data_width": 512,
    "beat_size_bytes": 64
  },
  "ports": {
    "m_axi": {
      "role": "master",
      "protocol": "aximm"
    }
  }
}
```

```json
"axis_checker": {
  "node_type": "AxisPacketCheckerSink",
  "params": {
    "expected_packets": 16,
    "check_mode": "exact",
    "ready_percent": 100
  },
  "ports": {
    "s_axis": {
      "role": "slave",
      "protocol": "axis"
    }
  }
}
```

`--param component.param=value` overrides write into this same component `params` dictionary. That means sweep-time overrides are component-level, not port-level.

## Port Config

Port config is any field under a port except `role` and `protocol`:

```json
"s_axi": {
  "role": "slave",
  "protocol": "aximm",
  "type": "ddr",
  "base_address": "0x0",
  "size": "0x100000000",
  "clock_domain_mhz": 300
}
```

Port config is used for endpoint-specific metadata:

- `clock_domain_mhz`
- memory `type`
- memory `base_address`
- memory `size`
- memory endpoint details such as DDR/HBM-related hints
- data-width hints used by topology generation in some paths

Use port config when the setting describes one logical NoC endpoint rather than the whole node.

## Connection Attributes

Connection attributes are extra fields on entries in `connections`:

```json
{
  "from": "tg_0.m_axi",
  "to": "bram_0.s_axi",
  "RequiredBW": 800,
  "RequiredLatency": 300
}
```

These are per-flow settings. They do not configure the endpoint SimObject. They influence generated route/path metadata in `.ncr` and `.nts`.

Supported QoS forms in the in-house generator:

```json
"RequiredBW": 800,
"RequiredLatency": 300
```

or:

```json
"qos": {
  "read_bw": 500,
  "write_bw": 500,
  "latency": 300
}
```

The in-house generator accepts both forms. The older Tcl/Vivado conversion path preserves nested `qos`, so use nested `qos` if the same file must work through that path.

## Clock Domain Rules

`clock_domain_mhz` can live in two places:

1. Port config:

```json
"m_axis": {
  "role": "master",
  "protocol": "axis",
  "clock_domain_mhz": 250
}
```

2. Component params:

```json
"params": {
  "clock_domain_mhz": 250
}
```

The resolved clock is per port endpoint. Resolution order:

1. `port.clock_domain_mhz`
2. `component.params.clock_domain_mhz`
3. global `--noc-clock`, converted to MHz

The setup code removes `clock_domain_mhz` before constructing the SimObject and passes resolved values through:

- `clockDomains`: vector of MHz values
- `port_endpoint_names`: vector of generated logical NoC endpoint names

For single-port components, component-level and port-level clocks are usually equivalent. For multi-port components, prefer port-level clocks when the ingress and egress sides can differ.

Example from the detailed file:

```json
"axis_fifo": {
  "node_type": "AxisFifoNode",
  "ports": {
    "s_axis": {
      "role": "slave",
      "protocol": "axis",
      "clock_domain_mhz": 200
    },
    "m_axis": {
      "role": "master",
      "protocol": "axis",
      "clock_domain_mhz": 250
    }
  }
}
```

## AXI-MM Endpoint Rules

AXI-MM uses `protocol: "aximm"`.

Common master component:

- `AxiRandomTrafficGenerator`

Common slave components:

- `BramEndpoint`
- `DdrMemoryController`
- `tileNSU_HBM`

AXI-MM master ports normally use `m_axi`. AXI-MM slave ports normally use `s_axi`.

Useful `AxiRandomTrafficGenerator` component params:

- `data_width`
- `beat_size_bytes`
- `min_transaction_size_bytes`
- `max_transaction_size_bytes`
- `transaction_size_distribution`
- `read_write_mode`
- `max_write_commands`
- `max_write_bandwidth_mbps`
- `max_read_bandwidth_mbps`
- `seed`
- `min_gap_cycles`
- `max_gap_cycles`
- `gap_distribution`
- `max_outstanding_writes`
- `address_distribution`
- `address_increment`
- `align_addresses`
- `nsu_selection`

Address ranges for AXI-MM targets come from generated topology metadata and from target `SysAddresses`. For memory-like AXI-MM slave ports, set `base_address` and `size` in port config.

AXI-MM master ports may also declare `base_address` plus `high_address` or
`size` when a traffic generator should use only a subrange of the target memory
window. Vivado programs those ranges onto the TG. gem5 applies the same
constraint by clipping the generated `nsu_min_addrs`/`nsu_address_spaces`
target windows to the master range. For fixed-size latency sweeps, the default
generator address step is the fixed `transaction_bytes` value when present;
explicit `param.<tg>.address_increment` overrides still win.

## AXIS Endpoint Rules

AXIS uses `protocol: "axis"`.

Common master components:

- `AxisRandomTrafficGenerator`
- `AxisPacketTrafficGenerator`
- `AxisFifoNode` on its `m_axis` port
- SmartNIC/RTL processing nodes on output ports

Common slave components:

- `AxisSinkNode`
- `AxisPacketCheckerSink`
- `AxisFifoNode` on its `s_axis` port
- SmartNIC/RTL processing nodes on input ports

Useful `AxisRandomTrafficGenerator` component params:

- `data_width`
- `tid_width`
- `tdest_width`
- `tuser_width`
- `packet_size_distribution`
- `min_packet_size_bytes`
- `max_packet_size_bytes`
- `gap_distribution`
- `min_gap_cycles`
- `max_gap_cycles`
- `tdest_distribution`
- `min_tdest`
- `max_tdest`
- `max_packets`

Useful `AxisPacketCheckerSink` component params:

- `data_width`
- `tid_width`
- `tdest_width`
- `tuser_width`
- `check_mode`
- `expected_packets`
- `ready_percent`
- `validate_ipv4_checksum`
- `validate_l4_checksum`
- `print_summary`
- `check_tdest`

AXIS has no address range. AXIS routing uses the generated tdest map and route metadata.

## DDR Rules

DDR memory endpoints are AXI-MM slaves.

Component naming rule:

```text
ddr<controller>_port0
```

Examples:

- `ddr0_port0`
- `ddr1_port0`

Only `port0` is currently supported by the v2 generator. The schema rejects other DDR port numbers.

Required port config:

```json
"ddr0_port0": {
  "node_type": "DdrMemoryController",
  "ports": {
    "s_axi": {
      "role": "slave",
      "protocol": "aximm",
      "type": "ddr",
      "base_address": "0x0",
      "size": "0x100000000"
    }
  }
}
```

Required/typical placement:

```json
"ddr0_port0.s_axi": "DDRMC_X2Y0"
```

Useful `ddr_settings` fields:

- `num_mc`: number of DDR controllers represented by the JSON
- `num_ports_per_mc`: currently must be `1`
- `controller_type`: example `DDR4_SDRAM`
- `speed_grade`: example `DDR4-3200AC(24-24-24)`
- `data_width`: controller data width, commonly `64`
- `memory_density`: example `8GB`
- `component_width`: example `x8`
- `rank`
- `slot`
- `stackheight`
- `interleave_size_bytes`

The schema checks that `ddr_settings.num_mc` matches the number of declared DDR controller ids when DDR ports are present.

## HBM Rules

HBM memory endpoints are AXI-MM slaves.

Component naming rule:

```text
hbm<controller>_port<0..3>
```

Examples:

- `hbm0_port0`
- `hbm0_port1`
- `hbm1_port0`

Required port config:

```json
"hbm0_port0": {
  "node_type": "tileNSU_HBM",
  "ports": {
    "s_axi": {
      "role": "slave",
      "protocol": "aximm",
      "type": "hbm",
      "base_address": "0x100000000",
      "size": "0x40000000"
    }
  }
}
```

Required/typical placement:

```json
"hbm0_port0.s_axi": "HBM_MC_X0Y0"
```

HBM pseudo-channel rule:

- ports `0` and `1` belong to pseudo channel `0`
- ports `2` and `3` belong to pseudo channel `1`

If two logical HBM ports are in the same pseudo channel, their `base_address` and `size` must agree. For example, `hbm0_port0` and `hbm0_port1` are both pseudo channel 0 and cannot declare conflicting ranges.

Useful `hbm_settings` fields currently seen in this tree:

- `num_pc`: number of pseudo channels exposed or expected by the run configuration
- HBM model/timing knobs may also be supplied by setup options or extended settings paths, depending on the run script

The `.nts` generator creates HBM logical memory instances and canonicalizes default zero-based placeholder ranges for multi-controller cases so gem5 does not build overlapping HBMCtrl ranges.

## Placement Physical Classes

Use the physical endpoint class that matches the logical endpoint:

| Logical endpoint | Physical endpoint |
| --- | --- |
| AXI-MM master | `NOC_NMU512_X...` or `NOC_NMU128_X...` |
| AXIS master | `NOC_NMU512_X...` or `NOC_NMU128_X...` |
| normal AXI-MM slave | `NOC_NSU512_X...` or `NOC_NSU128_X...` |
| normal AXIS slave | `NOC_NSU512_X...` or `NOC_NSU128_X...` |
| DDR memory slave | `DDRMC_X...` |
| HBM memory slave | `HBM_MC_X...` |

The runtime checks that the placement resolves to an endpoint with the expected protocol and role in the generated `.nts/.ncr` topology.

## Common Mistakes

- Referencing `tg_0` instead of `tg_0.m_axi` in a v2 `connections` entry.
- Putting a port-only setting such as a memory address range under component `params`.
- Putting a component SimObject parameter such as `expected_packets` under a port.
- Connecting AXI-MM directly to AXIS in one connection.
- Omitting a placement for one port of a multi-port component.
- Reusing one physical NMU/NSU endpoint for two logical ports.
- Using `hbm0_port0` and `hbm0_port1` with different ranges.
- Setting `ddr_settings.num_mc` to a value that does not match declared `ddrX_port0` components.
- Assuming component-level `clock_domain_mhz` is always per endpoint. It is only the fallback for every port on that component; port-level values override it.

## Quick Review Template

Use this checklist when reviewing a topology:

- Is the file `kind` correct?
- Is `version` `1`?
- Are all component ids unique and stable?
- Does every component have a valid `node_type`?
- Does every port have `role` and `protocol`?
- Are all connections `master -> slave`?
- Are protocols matched across every connection?
- Are per-flow settings on the connection, not the component?
- Are component parameters valid for that component's `node_type`?
- Are memory ranges on memory slave ports?
- Are clocks placed at the level intended by the design?
- Does placement cover every `component.port` endpoint?
- Does placement use NMU/NSU/HBM_MC/DDRMC classes correctly?
