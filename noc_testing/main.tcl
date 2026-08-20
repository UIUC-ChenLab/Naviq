# ======================= NoC TG Parameter Sweep — main ========================
# Usage:
#   vivado -mode batch -source main.tcl \
#          -tclargs csv sweep_plans/noc_plan_small.csv 

set tcl_echo_all 0

# === Anchor everything to the noc_testing folder (this file's directory) ===
set ::SWEEP_ROOT [file normalize [file dirname [info script]]]
puts "INFO: SWEEP_ROOT         = $::SWEEP_ROOT"

# Optional: allow an external orchestrator to set a common tag
if {[info exists ::env(RUN_TAG)] && $::env(RUN_TAG) ne ""} {
  set ::RESULTS_TAG $::env(RUN_TAG)
} else {
  set ::RESULTS_TAG [clock format [clock seconds] -gmt false -format "%Y%m%d_%H%M%S"]
}
puts "INFO: RESULTS_TAG        = $::RESULTS_TAG"

# Bring in libs from noc_testing/lib
# noc_aximm_project.tcl noc_axis_project.tcl
foreach f {noc_helpers.tcl noc_project.tcl noc_results.tcl noc_plan_csv.tcl} {
  source [file join $::SWEEP_ROOT lib $f]
}

set _cli_args $argv

if {[llength $_cli_args] == 0} {
  error "ERROR: No run mode specified. Usage: -tclargs <csv|csv_row> ..."
}

set RUN_MODE [string tolower [lindex $_cli_args 0]]

# Default values
set TESTPLAN_CSV ""
set RESULTS_CSV_OVERRIDE ""


if {$RUN_MODE eq "csv"} {
  # --- CSV Mode: Requires plan ---
  if {[llength $_cli_args] < 2} {
    error "ERROR: CSV mode requires a <plan.csv> file"
  }
  set TESTPLAN_CSV [file normalize [lindex $_cli_args 1]]
  
  if {![file exists $TESTPLAN_CSV]} {
    error "ERROR: Test plan not found at '$TESTPLAN_CSV'"
  }

  # Optional third argument is the results_csv override
  if {[llength $_cli_args] >= 3} {
    set arg3 [lindex $_cli_args 2]
    if {$arg3 ne ""} { set RESULTS_CSV_OVERRIDE [file normalize $arg3] }
  }
} elseif {$RUN_MODE eq "csv_row"} {
  if {[llength $_cli_args] < 3} {
    error "ERROR: csv_row mode requires a <plan.csv> file and a <row_index>."
  }
  set TESTPLAN_CSV [file normalize [lindex $_cli_args 1]]
  set ROW_INDEX [lindex $_cli_args 2]

  # Optional fourth argument is the results_csv override
  if {[llength $_cli_args] >= 4} {
    set arg4 [lindex $_cli_args 3]
    if {$arg4 ne ""} { set RESULTS_CSV_OVERRIDE [file normalize $arg4] }
  }

  if {![file exists $TESTPLAN_CSV]} {
    error "ERROR: Test plan not found at '$TESTPLAN_CSV'"
  }  
} elseif {$RUN_MODE eq "topology"} {
  # --- Topology-only Mode: Builds BD and exports NCR/NTS, no simulation ---
  if {[llength $_cli_args] < 2} {
    error "ERROR: topology mode requires a <plan.csv> file"
  }
  set TESTPLAN_CSV [file normalize [lindex $_cli_args 1]]
  
  if {![file exists $TESTPLAN_CSV]} {
    error "ERROR: Test plan not found at '$TESTPLAN_CSV'"
  }
} elseif {$RUN_MODE eq "topology_row"} {
  # --- Topology-row Mode: Builds BD and exports NCR/NTS for a single row ---
  if {[llength $_cli_args] < 3} {
    error "ERROR: topology_row mode requires <plan.csv> <row_index>"
  }
  set TESTPLAN_CSV [file normalize [lindex $_cli_args 1]]
  set ROW_INDEX [lindex $_cli_args 2]
  
  if {![file exists $TESTPLAN_CSV]} {
    error "ERROR: Test plan not found at '$TESTPLAN_CSV'"
  }
} else {
  error "ERROR: Unknown run mode '$RUN_MODE'. Must be 'csv', 'csv_row', 'topology', or 'topology_row'."
}

puts "INFO: RUN_MODE           = $RUN_MODE"
if {$TESTPLAN_CSV ne ""} { puts "INFO: TESTPLAN_CSV       = $TESTPLAN_CSV" }

# ---------------------- Results / Artifacts paths -------------------------
set ::ARTIFACTS_DIR [file join $::SWEEP_ROOT artifacts]
file mkdir $::ARTIFACTS_DIR
set ::RESULTS_DIR [file join $::ARTIFACTS_DIR results]
file mkdir $::RESULTS_DIR

if {$RESULTS_CSV_OVERRIDE ne ""} {
  set ::RESULTS_CSV $RESULTS_CSV_OVERRIDE
} else {
  set _plan_base [file rootname [file tail $TESTPLAN_CSV]]
  if {$_plan_base eq ""} { set _plan_base "results" }
  set ::RESULTS_CSV [file join $::RESULTS_DIR "vivado_${_plan_base}_${::RESULTS_TAG}.csv"]
}
puts "INFO: RESULTS_CSV        = $::RESULTS_CSV"

# ------------------------- TOP SETTINGS (edit me) ----------------------------
# Project lives under noc_testing/vivado_proj/noc_tg_sweep
set P [dict create \
  project_name  "noc_tg_sweep" \
  project_dir   [file join $::SWEEP_ROOT vivado_proj noc_tg_sweep] \
  part          "xcv80-lsva4737-2MHP-e-S" \
  board_part    "" \
  bd_name       "noc_subsystem" \
  sim_runtime   "100 s" \
]

# Fixed topology (kept constant during sweep)
dict set P num_aximm_tg       1
dict set P num_aximm_bram     1
dict set P noc_axi_clk_mhz  1000

# Optional QoS (kept constant)
dict set P qos_read_bw   500
dict set P qos_write_bw  500
dict set P qos_avg_burst 4

# Optional BRAM controller data width (0 => leave default)
dict set P tg_axi_data_width_bits  512
dict set P bram_data_width 512

# Optional custom NCR topology file from environment
if {[info exists ::env(CUSTOM_NCR_FILE)] && $::env(CUSTOM_NCR_FILE) ne ""} {
  dict set P custom_ncr [file normalize $::env(CUSTOM_NCR_FILE)]
  if {![file exists [dict get $P custom_ncr]]} {
    error "ERROR: CUSTOM_NCR_FILE does not exist: [dict get $P custom_ncr]"
  }
  puts "INFO: CUSTOM_NCR_FILE      = [dict get $P custom_ncr]"
}
if {[info exists ::env(CUSTOM_NTS_FILE)] && $::env(CUSTOM_NTS_FILE) ne ""} {
  dict set P custom_nts [file normalize $::env(CUSTOM_NTS_FILE)]
  if {![file exists [dict get $P custom_nts]]} {
    error "ERROR: CUSTOM_NTS_FILE does not exist: [dict get $P custom_nts]"
  }
  puts "INFO: CUSTOM_NTS_FILE      = [dict get $P custom_nts]"
}

# ---------------------------- Defaults & Specs ------------------------------
# Baseline TG defaults
set TG_DEFAULTS [dict create \
  USER_C_AXI_NO_OF_WR_TRANS   50 \
  USER_C_AXI_NO_OF_RD_TRANS   50 \
  USER_C_AXI_WRITE_BANDWIDTH  800 \
  USER_C_AXI_WRITE_LEN        16 \
  USER_C_AXI_WRITE_SIZE       16 \
]

# Exit Vivado when done
set EXIT_WHEN_DONE 1

# ------------------------------- RUN -----------------------------------------
if {$RUN_MODE eq "csv"} {
  # CSV-driven sweep (recommended)
  puts "INFO: Starting CSV-driven sweep..."
  sweep_from_csv $P $TG_DEFAULTS $TESTPLAN_CSV $::RESULTS_CSV
} elseif {$RUN_MODE eq "csv_row"} {
  puts "INFO: Starting single row run from CSV..."
  run_single_row_from_csv $P $TG_DEFAULTS $TESTPLAN_CSV $ROW_INDEX $::RESULTS_CSV
} elseif {$RUN_MODE eq "topology"} {
  puts "INFO: Starting topology-only generation (no simulation)..."
  generate_topology_from_csv $P $TESTPLAN_CSV
} elseif {$RUN_MODE eq "topology_row"} {
  puts "INFO: Generating topology for single row $ROW_INDEX..."
  generate_topology_for_row $P $TESTPLAN_CSV $ROW_INDEX
} 
if {$EXIT_WHEN_DONE} { quit }
