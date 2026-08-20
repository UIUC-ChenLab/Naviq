# Connection And Placement JSON Guide

This directory contains Naviq v2 topology inputs. The two main file types are:

- `*.conn.json`: logical setup. This says what components exist, which ports they expose, and which master ports talk to which slave ports.
- `*.place.json`: physical placement. This maps each logical `component.port` endpoint onto a physical Versal NoC endpoint such as `NOC_NMU512_X0Y0`, `NOC_NSU512_X0Y0`, `HBM_MC_X0Y0`, or `DDRMC_X2Y0`.

Start with these examples:

- Simple AXI-MM example: `examples/simple_aximm_1to1.conn.json` and `examples/simple_aximm_1to1.place.json`
- Detailed mixed AXI-MM/AXIS, DDR/HBM, QoS, and clock example: `examples/detailed_mixed_clocked.conn.json` and `examples/detailed_mixed_clocked.place.json`

For lower-level settings, memory endpoint rules, and clock-domain details, see `SETTINGS_AND_ENDPOINT_REFERENCE.md`.

## Big Picture

A connection JSON describes the logical system. It does not by itself choose physical routes. A placement JSON maps each logical port to a physical NoC endpoint. The in-house topology generator uses both files to emit `.ncr` and `.nts` files, and gem5 uses the original JSON plus those generated route artifacts.

The practical flow is:

1. Write a `*.conn.json`.
2. Write a matching `*.place.json`, or let the in-house placer generate one.
3. Generate `.ncr` and `.nts` artifacts with `noc_testing/tools/topology/generate_ncr.py` or through `noc_testing/noc_sweep.py --topo-gen in_house`.
4. Run gem5 with `--connections-json`, `--placement-json`, and `--noc-topology`.

## Connection JSON Shape

Every v2 connection JSON should start with:

```json
{
  "kind": "naviq.connections",
  "version": 1,
  "name": "my_topology",
  "components": {},
  "connections": []
}
```

`kind` and `version` are required by the schema. `name` is a human-readable label. Use a stable, filename-like name because sweep scripts often use names to build artifact keys.

## Components

`components` is an object keyed by logical component id:

```json
"tg_0": {
  "node_type": "AxiRandomTrafficGenerator",
  "params": {
    "max_write_commands": 16,
    "data_width": 512
  },
  "ports": {
    "m_axi": {
      "role": "master",
      "protocol": "aximm"
    }
  }
}
```

Each component needs:

- `node_type`: the gem5 SimObject class to instantiate.
- `ports`: one or more named ports.
- `params`: optional component-level SimObject parameters.

Component ids are logical names. They do not need to match physical NoC endpoint names. Prefer short descriptive ids like `tg_0`, `bram_0`, `axis_fifo`, `ddr0_port0`, or `hbm0_port0`.

## Ports

Every port must define:

- `role`: `master` or `slave`
- `protocol`: `aximm` or `axis`

The full endpoint name is always `component_id.port_name`. For example:

- `tg_0.m_axi`
- `bram_0.s_axi`
- `axis_fifo.s_axis`
- `axis_fifo.m_axis`

Use conventional port names when possible:

- AXI-MM master: `m_axi`
- AXI-MM slave: `s_axi`
- AXIS master: `m_axis`
- AXIS slave: `s_axis`

Extra fields inside a port are treated as port config. This is where endpoint-specific metadata lives, such as `base_address`, `size`, `type`, and per-port `clock_domain_mhz`.

## Connections

`connections` is a list of logical flows:

```json
{
  "from": "tg_0.m_axi",
  "to": "bram_0.s_axi"
}
```

Rules:

- `from` must reference a known master endpoint.
- `to` must reference a known slave endpoint.
- `from` and `to` must use the same protocol.
- AXI-MM and AXIS cannot be directly connected in one connection entry.
- A master may connect to multiple slaves.
- Multiple masters may connect to one slave.
- Multi-hop logical chains are expressed as separate connections. For example, source to FIFO input, then FIFO output to sink.

Example AXIS chain:

```json
[
  { "from": "axis_source.m_axis", "to": "axis_fifo.s_axis" },
  { "from": "axis_fifo.m_axis", "to": "axis_sink.s_axis" }
]
```

Per-flow route/QoS fields can also live on a connection:

```json
{
  "from": "tg_0.m_axi",
  "to": "bram_0.s_axi",
  "RequiredBW": 800,
  "RequiredLatency": 300
}
```

The generator also accepts nested QoS:

```json
{
  "from": "tg_0.m_axi",
  "to": "bram_0.s_axi",
  "qos": {
    "read_bw": 500,
    "write_bw": 500,
    "latency": 300
  }
}
```

Prefer direct `RequiredBW` and `RequiredLatency` for new in-house-generator-only files. Use nested `qos` if the file also needs to travel through older Tcl/Vivado compatibility paths.

## Placement JSON Shape

A placement JSON maps every endpoint from the connection JSON:

```json
{
  "kind": "naviq.placement",
  "version": 1,
  "name": "my_topology",
  "placements": {
    "tg_0.m_axi": "NOC_NMU512_X0Y0",
    "bram_0.s_axi": "NOC_NSU512_X0Y0"
  }
}
```

Rules:

- Every endpoint in the connection JSON must be present.
- Master ports should map to `NOC_NMU...` endpoints.
- Normal AXI-MM or AXIS slave ports should map to `NOC_NSU...` endpoints.
- HBM memory ports should map to `HBM_MC...` endpoints.
- DDR memory ports should map to `DDRMC...` endpoints.
- Do not map two logical endpoints to the same physical endpoint unless the underlying generated topology and runtime support that specific sharing case. Most normal NMU/NSU endpoints should be used once.

## Parameters

There are three common places for settings:

1. Component `params`
   These become SimObject constructor parameters for the whole component.

2. Port config
   Extra fields under a port become endpoint-specific metadata. Memory address ranges and per-port clocks live here.

3. Connection attrs
   Extra fields on a `connections` entry are per-flow route/QoS metadata.

Example:

```json
"axis_fifo": {
  "node_type": "AxisFifoNode",
  "params": {
    "fifo_depth": 512,
    "expected_packets": 16
  },
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

Here `fifo_depth` and `expected_packets` configure the `AxisFifoNode`. The two `clock_domain_mhz` values configure the two logical NoC endpoints of that node.

## Clock Domains

Clocking is endpoint-oriented in the v2 setup path. The resolved clock is stored in the node's `clockDomains` vector in port order, alongside `port_endpoint_names`.

Clock precedence is:

1. Port-level `clock_domain_mhz`
2. Component-level `params.clock_domain_mhz`
3. Global `--noc-clock`, converted to MHz

Use component-level `clock_domain_mhz` when every port on a component runs at the same clock. Use port-level `clock_domain_mhz` when a multi-port component has different clock domains on different ports.

Example:

```json
"axis_fifo": {
  "node_type": "AxisFifoNode",
  "params": {
    "clock_domain_mhz": 200,
    "fifo_depth": 512
  },
  "ports": {
    "s_axis": {
      "role": "slave",
      "protocol": "axis"
    },
    "m_axis": {
      "role": "master",
      "protocol": "axis",
      "clock_domain_mhz": 250
    }
  }
}
```

In this example, `s_axis` inherits 200 MHz from the component, and `m_axis` overrides to 250 MHz.

## Naming And Organization

Suggested conventions:

- Put simple reusable examples under `basic/`.
- Put AXIS-focused examples under `axis/`.
- Put DDR-focused examples under `ddr/`.
- Put HBM-focused examples under `hbm/`.
- Put experiment-specific cases under `multi_endpoint/`, `placement_tests/`, or a dedicated experiment directory.
- Keep examples and instructional files under `examples/` if they are not meant to be production sweep inputs.

Use paired names when the placement is specific to one connection file:

- `my_case.conn.json`
- `my_case.place.json`

Use descriptive placement names when the placement is intentionally reused:

- `4nmu_to_1nsu_incast_aximm.conn.json`
- `4nmu_to_1nsu_incast_compact.place.json`
- `4nmu_to_1nsu_incast_spread.place.json`

## Validation Checklist

Before using a new topology:

- Run `python3 -m json.tool path/to/file.json` on both files.
- Confirm every connection endpoint exists in `components`.
- Confirm every `from` endpoint is a master.
- Confirm every `to` endpoint is a slave.
- Confirm each connection stays within one protocol.
- Confirm every endpoint has a placement.
- Confirm physical placements use the right physical class: NMU for masters, NSU for normal slaves, HBM_MC for HBM, DDRMC for DDR.
- For memory endpoints, confirm `base_address` and `size` are present and non-overlapping unless the sharing is intentional.
- For clocks, decide whether the clock should be global, component-level, or port-level.
