# V2 Memory Endpoint Contract

This document defines the recommended V2 JSON contract for memory endpoints used
by `noc_testing` and `generate_ncr.py`.

## Memory Type Keywords

Use the slave AXI-MM port `type` field to distinguish memory endpoint kinds:

- `type: "hbm"`
- `type: "ddr"`

Memory endpoint ports must be:

- `role: "slave"`
- `protocol: "aximm"`

## HBM Contract

HBM endpoint component IDs must follow:

- `hbm<controller>_port<0..3>`

Examples:

- `hbm0_port0`
- `hbm0_port1`
- `hbm1_port2`

HBM ports imply pseudo-channel membership:

- `PORT0`, `PORT1` -> pseudo-channel 0
- `PORT2`, `PORT3` -> pseudo-channel 1

Required slave-port fields:

- `type`
- `base_address`
- `size`

Recommended top-level settings:

- `hbm_settings.read_latency_cycles`
- `hbm_settings.write_latency_cycles`
- `hbm_settings.resp_latency_cycles`
- `hbm_settings.shared_bw_MBps`
- `hbm_settings.port_queue_depth`
- `hbm_settings.max_outstanding_reads`
- `hbm_settings.max_outstanding_writes`
- `hbm_settings.issue_interval_cycles`
- `hbm_settings.banks_per_pseudo_channel`
- `hbm_settings.row_hit_latency_cycles`
- `hbm_settings.row_miss_latency_cycles`
- `hbm_settings.bank_busy_cycles`
- `hbm_settings.cmd_bus_cycles`
- `hbm_settings.page_policy`
- `hbm_settings.arb_policy`

Compatibility note:

- `hbm_settings.num_pc` is still accepted, but explicit endpoint naming is the
  primary source of truth for controller, port, and pseudo-channel identity.

## DDR Contract

DDR endpoint component IDs must follow:

- `ddr<controller>_port<port>`

The current V2 generator supports one exposed DDR port per controller:

- `ddr<controller>_port0`

Example:

- `ddr0_port0`

Required slave-port fields:

- `type`
- `base_address`
- `size`

Recommended top-level settings:

- `ddr_settings.num_mc`
- `ddr_settings.num_ports_per_mc`
- `ddr_settings.controller_type`
- `ddr_settings.speed_grade`
- `ddr_settings.data_width`
- `ddr_settings.memory_density`

## Validation Rules

The shared setup schema now rejects:

- HBM endpoints whose component IDs do not match `hbm<controller>_port<0..3>`
- DDR endpoints whose component IDs do not match `ddr<controller>_port<port>`
- memory endpoints missing `base_address` or `size`
- memory endpoints that are not AXI-MM slave ports
- HBM pseudo-channel range conflicts within a controller
- DDR configurations requesting unsupported multi-port exposure
