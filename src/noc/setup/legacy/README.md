# Legacy setup scripts

These scripts are retained as historical CPU and system-configuration
references. They are not supported public entry points for new NoC work; use
`src/noc/setup/noc_config.py`, the TestLib scenarios, or an experiment manifest
instead.

Several scripts (`noc_config_cpu_test.py`, `noc_config_bridge_tg.py`,
`noc_config_fs.py`, and `noc_config_old_test.py`) contain an old HBM-NMU path
that instantiates the archived, unregistered `tile` SimObject. That path must
not be used or described as supported. The released HBM path uses canonical
`mmNocMasterUnit` setup with `tileNSU_HBM` endpoints.

Keep a legacy script only while it has a validated replacement plan. Before
promoting any of these flows, add a documented command and a deterministic
regression using the supported configuration path.
