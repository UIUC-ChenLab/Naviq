# ======================== Results / CSV (Refactored) =========================

# A single, robust function to parse the entire simulation log.
# It intelligently combines the TEST REPORT and PMON sections for each SRC_ID.
# Returns a dictionary where keys are SRC_IDs and values are dictionaries of metrics.
proc _parse_simulation_log {log_text} {
  set src_map [dict create]
  set current_sid ""

  foreach line [split $log_text "\n"] {
    # Check for a new SRC_ID header
    if {[regexp {^>>+\s*SRC\s*_?ID\s+([0-9]+)} $line -> sid]} {
      set current_sid $sid
      if {![dict exists $src_map $current_sid]} {
        dict set $src_map $current_sid [dict create]
      }
    }
    if {$current_sid eq ""} { continue }

    # --- PMON Section Parsing ---
    if {[regexp {^Min Write Latency\s*=\s*([0-9.]+)} $line -> val]} { dict set src_map $current_sid write_latency_min $val; continue }
    if {[regexp {^Max Write Latency\s*=\s*([0-9.]+)} $line -> val]} { dict set src_map $current_sid write_latency_max $val; continue }
    if {[regexp {^Avg Write Latency\s*=\s*([0-9.]+)} $line -> val]} { dict set src_map $current_sid write_latency_avg $val; continue }
    if {[regexp {^Actual Achieved Write Bandwidth\s*=\s*([0-9.]+)} $line -> val]} { dict set src_map $current_sid achieved_write_bandwidth_MBps $val; continue }
    if {[regexp {^Min Read Latency\s*=\s*([0-9.]+)} $line -> val]} { dict set src_map $current_sid read_latency_min $val; continue }
    if {[regexp {^Max Read Latency\s*=\s*([0-9.]+)} $line -> val]} { dict set src_map $current_sid read_latency_max $val; continue }
    if {[regexp {^Avg Read Latency\s*=\s*([0-9.]+)} $line -> val]} { dict set src_map $current_sid read_latency_avg $val; continue }
    if {[regexp {^Actual Achieved Read Bandwidth\s*=\s*([0-9.]+)} $line -> val]} { dict set src_map $current_sid achieved_read_bandwidth_MBps $val; continue }

    # --- TEST REPORT Section Parsing ---
    if {[regexp {\[INFO\].*AXI_CLK_PERIOD\s*=\s*([0-9]+)ps} $line -> val]} { dict set src_map $current_sid axi_clk_period_ps $val; continue }
    if {[regexp {\[INFO\].*AXI_DATAWIDTH\s*=\s*([0-9]+)bit} $line -> val]} { dict set src_map $current_sid axi_data_width_bits $val; continue }
    if {[regexp {\[INFO\].*TEST_STATUS\s*=\s*(.+)$} $line -> val]} { dict set src_map $current_sid test_status [string trim $val]; continue }
    # Map TOTAL_PACKET_SENT to write_req_total
    if {[regexp {\[INFO\].*TOTAL_PACKET_SENT\s*=\s*([0-9]+)} $line -> val]} { dict set src_map $current_sid write_req_total $val; continue }
    # Also handle the AXI-MM version for backward compatibility
    if {[regexp {\[INFO\].*TOTAL_WRITE_REQ_SENT\s*=\s*([0-9]+)} $line -> val]} { dict set src_map $current_sid write_req_total $val; continue }
    if {[regexp {\[INFO\].*TOTAL_READ_REQ_SENT\s*=\s*([0-9]+)} $line -> val]} { dict set src_map $current_sid read_req_total $val; continue }
  }
  return $src_map
}

# A generic helper to append rows to a CSV file.
# It ensures columns are always written in the correct order.
proc _append_csv_rows {csv_path headers rows} {
  set need_header [expr {![file exists $csv_path] || [file size $csv_path] == 0}]
  file mkdir [file dirname $csv_path]
  set f [open $csv_path a]
  if {$need_header} {
    puts $f [join $headers ","]
  }
  foreach r $rows {
    set values {}
    foreach h $headers {
      lappend values [_dget $r $h ""]
    }
    puts $f [join $values ","]
  }
  close $f
}

# The main coordinator function, now much cleaner.
# It defines what goes in the CSV, parses the log, builds the rows, and writes them.
proc collect_sim_results_to_csv {P combo note {csv_out ""} {sim_secs ""}} {
  # --- 1. Define the CSV Structure ---
  set headers {
    finished_at_iso name sim_time_s src_id tg_mode 
    num_aximm_tg num_aximm_bram num_axis_tg num_axis_end
    num_write_transactions_cfg axi_write_size_bytes axi_write_len_beats axi_write_bandwidth_cfg_MBps
    achieved_write_bandwidth_MBps write_latency_min write_latency_max write_latency_avg
    achieved_read_bandwidth_MBps  read_latency_min  read_latency_max  read_latency_avg
    write_req_total read_req_total num_read_transactions_cfg
    axi_clk_period_ps tg_axi_data_width_bits endpoint_data_width_bits
    qos_read_bw_MBps qos_write_bw_MBps qos_avg_burst test_status
  }

  # --- 2. Parse the Simulation Log ---
  set simlog_path [file join [dict get $P project_dir] "[dict get $P project_name].sim/sim_1/behav/xsim/simulate.log"]
  if {![file exists $simlog_path]} {
    puts "WARN: simulate.log not found at $simlog_path"
    return
  }
  set src_map [_parse_simulation_log [read [open $simlog_path r]]]

  # If nothing was parsed, write a placeholder row to track the run
  if {[dict size $src_map] == 0} {
    puts "WARN: No SRC_ID blocks parsed from log; writing a placeholder row."
    set src_map [dict create -1 [dict create]]
  }

  if {$sim_secs eq ""} {
    set viv_log_path [_vivado_log_path $P]
    if {[file exists $viv_log_path]} {
      set f [open $viv_log_path r]
      set log_text [read $f]
      close $f
      set sim_secs [_parse_elapsed_seconds $log_text]
    }
  }

  # --- 3. Build the Row Dictionaries ---
  set finished_at [_now_iso]
  set rows_to_write {}
  foreach sid [lsort -integer [dict keys $src_map]] {
    set parsed_metrics [dict get $src_map $sid]
    set row [dict create]

    # Add metadata
    dict set row finished_at_iso $finished_at
    dict set row src_id $sid
    dict set row name $note
    dict set row sim_time_s $sim_secs

    # --- Add topology info from P dictionary (UPDATED) ---
    # Use _dget to safely get counts, defaulting to 0
    dict set row num_aximm_tg      [_dget $P num_aximm_tg 0]
    dict set row num_aximm_bram    [_dget $P num_aximm_bram 0]
    dict set row num_axis_tg       [_dget $P num_axis_tg 0]
    dict set row num_axis_end      [_dget $P num_axis_end 0]
    
    dict set row endpoint_data_width_bits [_dget $P bram_data_width 0]
    dict set row qos_read_bw_MBps     [_dget $P qos_read_bw ""]
    dict set row qos_write_bw_MBps    [_dget $P qos_write_bw ""]
    dict set row qos_avg_burst        [_dget $P qos_avg_burst ""]
    if {[dict exists $P tg_axi_data_width_bits]} {
        dict set row tg_axi_data_width_bits [dict get $P tg_axi_data_width_bits]
    }

    # Add TG config from combo dictionary
    dict set row tg_mode [_dget $combo __tg_mode ""]
    dict set row axi_write_size_bytes [_dget $combo USER_C_AXI_WRITE_SIZE ""]
    dict set row axi_write_len_beats [_dget $combo USER_C_AXI_WRITE_LEN ""]
    dict set row axi_write_bandwidth_cfg_MBps [_dget $combo USER_C_AXI_WRITE_BANDWIDTH ""]
    dict set row num_write_transactions_cfg [_dget $combo USER_C_AXI_NO_OF_WR_TRANS ""]
    dict set row num_read_transactions_cfg [_dget $combo USER_C_AXI_NO_OF_RD_TRANS ""]

    # Add the parsed metrics from the log file
    set row [dict merge $row $parsed_metrics]

    lappend rows_to_write $row
  }

  # --- 4. Write to the CSV File ---
  if {$csv_out eq ""} { set csv_out $::RESULTS_CSV }
  _append_csv_rows $csv_out $headers $rows_to_write
  puts "INFO: Wrote [llength $rows_to_write] row(s) to $csv_out"
}

# --- Utility Procs ---
proc _now_iso {} {
  return [clock format [clock seconds] -gmt false -format "%Y-%m-%dT%H:%M:%S%z"]
}
# Tcl 8.7+ has `dict getwithdefault`, but Vivado uses 8.6.
# This is a safe way to get a value or a default if the key is missing.
proc _dget {dict key {default ""}} {
  if {[dict exists $dict $key]} {
    return [dict get $dict $key]
  }
  return $default
}

proc _copy_sim_log {P note} {
  set simlog [file normalize [file join [dict get $P project_dir] "[dict get $P project_name].sim/sim_1/behav/xsim/simulate.log"]]
  if {![file exists $simlog]} { return }
  
  set tag [expr {[info exists ::RESULTS_TAG] ? $::RESULTS_TAG : [clock format [clock seconds] -format "%Y%m%d_%H%M%S"]}]
  set outdir [file join $::SWEEP_ROOT "artifacts" "simlogs" "simlogs_$tag"]
  file mkdir $outdir
  
  set fname [string map {" " "_" "," "_" ":" "_" "/" "_"} $note]
  file copy -force $simlog [file join $outdir "Vivado_${fname}.log"]
}

proc _vivado_log_path {P} {
  # Prefer the project dir, then fall back to workspace root
  set p1 [file normalize [file join [dict get $P project_dir] "vivado.log"]]
  if {[file exists $p1]} { return $p1 }
  set p2 [file normalize [file join [pwd] "vivado.log"]]
  return $p2
}

proc _parse_elapsed_seconds {vivado_log_text} {
  set secs ""
  foreach l [split $vivado_log_text "\n"] {
    # Match format: elapsed = 00:01:09
    if {[regexp -nocase {elapsed\s*=\s*([0-9]{1,2}):([0-9]{2}):([0-9]{2})} $l -> H M S]} {
      scan $H %d H10; scan $M %d M10; scan $S %d S10
      set secs [expr {$H10*3600 + $M10*60 + $S10}]
      continue
    }
    # Match format: elapsed = 45 s
    if {[regexp -nocase {elapsed\s*=\s*([0-9]+)\s*s\b} $l -> Sonly]} {
      scan $Sonly %d S10
      set secs $S10
      continue
    }
  }
  return $secs
}