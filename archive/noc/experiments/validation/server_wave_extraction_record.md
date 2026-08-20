# Historical Server Wave Extraction Record

> **Archived record (2026-08-16).** This procedure documents a past
> Vivado/XSim investigation. Confirm all paths, versions, and acceptance
> criteria before reusing it. The maintained validation entry point is
> `noc_testing/experiments/validation/README.md`.

## Goal

Run automated Vivado/XSim waveform CSV extraction for the multi-endpoint incast debug on a Linux server with Vivado 2025.x. Avoid manual GUI waveform inspection unless the automated Tcl path cannot find the required internal HDL objects.

## Background

The local WSL/Vivado 2024.2 environment is blocked before any NoC-specific logic runs. Even a trivial Verilog snapshot fails at XSim load:

```text
# xsim {tb_smoke} -autoloadwcfg -runall
ERROR: unexpected exception when evaluating tcl command
```

This means the local failure is below the Naviq Tcl sampler and below the NoC design. UG900 confirms the intended flow is valid:

```sh
xsim <snapshot> -tclbatch run.tcl
```

The server should first prove that XSim can run a trivial snapshot. If it can, proceed to the automated incast wave probe.

## Relevant Source Changes To Bring To Server

These files contain the optional wave CSV plumbing and probe plans:

- `noc_testing/lib/noc_project.tcl`
- `noc_testing/lib/noc_plan_csv.tcl`
- `noc_testing/sweep_plans/validation/vivado_naviq_incast_wave_control.csv`
- `noc_testing/sweep_plans/validation/vivado_naviq_incast_wave_probe.csv`
- `archive/noc/experiments/validation/server_wave_extraction_record.md`

The local modifications below were present during the original investigation,
but are not required for the server wave probe:

- `noc_testing/experiments/validation/README.md`
- `archive/noc/experiments/validation/incast_validation_record.md`
- `noc_testing/experiments/validation/analyze_incast_traces.py`
- `noc_testing/experiments/validation/export_vivado_nps_wave_csv.tcl`

## Step 1: Enter Repo And Confirm Vivado

```sh
cd /path/to/Naviq
vivado -version
xsim -version
```

Record the Vivado/XSim version in the final notes.

## Step 2: Run Trivial XSim Smoke Test

Create a temporary smoke directory outside source control if it does not already exist:

```sh
mkdir -p /tmp/naviq_xsim_smoke
cd /tmp/naviq_xsim_smoke
cat > tb.v <<'EOF'
module tb;
  initial begin
    $display("naviq_xsim_smoke_ok");
    $finish;
  end
endmodule
EOF

xvlog tb.v
xelab tb -s tb_smoke
xsim tb_smoke -R -log xsim_smoke.log
```

Expected pass:

```text
naviq_xsim_smoke_ok
```

If this fails with `unexpected exception when evaluating tcl command`, stop. The server XSim environment is not usable for automated waveform extraction yet. Do not continue into NoC runs.

## Step 3: Run Vivado Incast Control

Return to the Naviq repo:

```sh
cd /path/to/Naviq
RUN_TAG=wave_control_server \
timeout 1200 vivado -mode batch -source noc_testing/main.tcl -tclargs \
  csv_row \
  noc_testing/sweep_plans/validation/vivado_naviq_incast_wave_control.csv \
  1 \
  noc_testing/artifacts/generated/results/vivado_results_wave_control_server.csv
```

Expected pass:

- Vivado exits with code 0.
- Results CSV exists:
  `noc_testing/artifacts/generated/results/vivado_results_wave_control_server.csv`
- No `unexpected exception when evaluating tcl command` appears in logs.

If this fails after the trivial smoke passed, inspect:

```sh
find noc_testing/vivado_proj -name simulate.log -o -name xsim.jou -o -name elaborate.log -o -name compile.log
```

Summarize the first real error. Do not start the wave probe until the control row runs.

## Step 4: Run Vivado Incast Wave Probe

```sh
cd /path/to/Naviq
RUN_TAG=wave_probe_server \
timeout 1200 vivado -mode batch -source noc_testing/main.tcl -tclargs \
  csv_row \
  noc_testing/sweep_plans/validation/vivado_naviq_incast_wave_probe.csv \
  1 \
  noc_testing/artifacts/generated/results/vivado_results_wave_probe_server.csv
```

The probe targets these logical merge points from the shared `.ncr`:

- `NOC_NPS_VNOC_X1Y18`
- `NOC_NPS7575_X5Y0`
- `NOC_NPS_VNOC_X1Y0`

The Tcl plumbing expands these logical names to generated Vivado aliases such as:

- `nps_30` / `xlnoc_nps_30_0`
- `nps_34` / `xlnoc_nps_34_0`
- `nps_0` / `xlnoc_nps_0_0`

Expected artifacts:

```text
noc_testing/artifacts/vivado_wave_csv/wave_probe_server/4to1_std_tx10_wave_probe.csv
noc_testing/artifacts/vivado_wave_csv/wave_probe_server/4to1_std_tx10_wave_probe.csv.inventory
noc_testing/artifacts/vivado_wave_csv/wave_probe_server/4to1_std_tx10_wave_probe.csv.xsim.tcl
```

Acceptance for the probe:

- Vivado exits with code 0.
- The wave CSV exists and has more than just the header.
- The inventory file exists and contains objects under the targeted NPS aliases.
- The result CSV still exists:
  `noc_testing/artifacts/generated/results/vivado_results_wave_probe_server.csv`

Quick checks:

```sh
wc -l noc_testing/artifacts/vivado_wave_csv/wave_probe_server/4to1_std_tx10_wave_probe.csv
head -5 noc_testing/artifacts/vivado_wave_csv/wave_probe_server/4to1_std_tx10_wave_probe.csv
rg -n "xlnoc_nps|nps_|ready|valid|grant|queue|aw|w|b|ar|r" \
  noc_testing/artifacts/vivado_wave_csv/wave_probe_server/4to1_std_tx10_wave_probe.csv.inventory
```

## Step 5: If CSV Is Header-Only

If the probe runs but the CSV has only a header, the automated path is working but the signal filters are too narrow or the generated hierarchy differs on the server.

Do this next:

1. Inspect the `.inventory` file.
2. Identify the actual HDL object paths for the three NPS aliases.
3. Broaden `vivado_wave_signals` in `vivado_naviq_incast_wave_probe.csv`, for example:

```text
ready|valid|grant|queue|depth|credit|stall|aw|w|b|ar|r|m_|s_|axis|axi
```

4. Rerun only the wave probe row.

Do not manually use the GUI until the inventory proves the Tcl sampler cannot see the required objects.

## Step 6: Compare Against Naviq/Gem5

Once the Vivado CSV exists, compare it to the gem5/Naviq traces for `4to1_std_tx10` first.

Primary questions:

- Do all four sources inject at the same expected times?
- At the final merge NPS, does Vivado serialize sources in an order Naviq does not reproduce?
- Are AW/W/B and AR/R ready-valid boundaries shifted by a stable amount?
- Are queues mostly empty in Naviq while Vivado shows arbitration or backpressure?

Only after `4to1_std_tx10` has a concrete divergence point should the same probe be extended to `4to1_sat_tx10`.

## Decision Criteria

- If capped Naviq queues are mostly empty while Vivado shows merge ordering, prioritize bursty capped injection / `AvgBurst=4` modeling.
- If both tools queue similarly but Naviq latency tracks hop count too strongly, prioritize NPS per-hop latency recalibration.
- If all timing is offset by a stable amount, prioritize `NocTrafficMonitor` versus Vivado PMON boundary alignment.
- If saturated write paths match but read responses diverge, isolate read-response queueing at NSU, final NPS, or NMU before changing write behavior.

## What To Report Back

Report:

- Vivado/XSim version.
- Whether the trivial XSim smoke passed.
- Whether the incast control passed.
- Whether the wave probe produced a non-empty CSV.
- Exact artifact paths.
- First failing command and first real error, if any.
