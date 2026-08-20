# NoC setup support modules

This directory is Python configuration support, not C++ header files. It is
kept as a stable compatibility location because the public configuration and
several historical setup scripts import these modules directly.

| Module | Responsibility |
| --- | --- |
| `noc_config_funcs.py` | Shared option parsing, topology/address loading, endpoint construction, metrics output, clock policy, and probe wiring. |
| `noc_network.py` | NoC network and endpoint-interface construction. |
| `noc_trace_paths.py` | Caller-selected runtime trace and graph output paths. |
| `noc_graphs.py` | Optional post-run graph and heatmap helpers. |

`noc_config_funcs.py` has intentional section boundaries for metrics, timing,
topology parsing, endpoint construction, and probe wiring. Extract a section
only behind a compatibility import and a configuration import test; many legacy
scripts currently import its public helpers directly.
