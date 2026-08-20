# Vendored SystemVerilogAXI sources

This directory contains the C++ AXI and AXIS traffic-generator sources used
by Naviq. They were vendored from `scottcs2/SystemVerilogAXI` commit
`d24e384c92369f8bbdcad597c2939cd13b4f70ba` so a Naviq checkout is
self-contained.

Only the source and header dependency closure compiled by
`src/noc/SConscript` is included. Standalone executables, SystemVerilog test
wrappers, editor configuration, and upstream tests are intentionally omitted.

The vendored code is distributed under the Apache License 2.0 in `LICENSE`.
The bundled nlohmann JSON header retains its own license in
`axi_traffic/include/json/license.txt`.
