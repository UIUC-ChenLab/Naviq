# ============================ CSV Test Plan ==================================
# Simple CSV reader (no commas inside fields please). Supports:
# - header in first line
# - blank lines & lines starting with '#' are ignored
proc _csv_read_rows {path} {
  if {![file exists $path]} { error "CSV not found: $path" }
  set f [open $path r]
  set header {}
  set rows {}

  while {[gets $f line] >= 0} {
    set line [string trim $line]
    if {$line eq ""} continue
    if {[string match "#*" $line]} continue

    if {$header eq ""} {
      set header [lmap h [split $line ,] {string trim $h}]
      continue
    }
    set vals [lmap v [split $line ,] {string trim $v}]
    # Pad/truncate to header length
    while {[llength $vals] < [llength $header]} { lappend vals "" }
    set vals [lrange $vals 0 [expr {[llength $header]-1}]]

    set d [dict create]
    for {set i 0} {$i < [llength $header]} {incr i} {
      dict set d [lindex $header $i] [lindex $vals $i]
    }
    lappend rows $d
  }
  close $f
  return $rows
}

# Safe number coercion (returns "" if not numeric)
proc _to_int {s} {
  set s [string trim $s]
  if {$s eq ""} { return "" }
  if {![string is integer -strict $s]} { return "" }
  return $s
}

proc _to_string {s} {
  return [string trim $s]
}

# Extract topology overrides from a CSV row (only keys present will override P)
proc _topology_from_row {row} {
  set topo {}
  foreach {csvk pk coerce} {
    num_axi_tg          num_aximm_tg        _to_int
    num_axi_bram        num_aximm_bram      _to_int
    num_aximm_tg        num_aximm_tg        _to_int
    num_aximm_bram      num_aximm_bram      _to_int
    num_axis_tg         num_axis_tg         _to_int
    num_axis_end        num_axis_end        _to_int
    num_axis_endpoints  num_axis_end        _to_int
    noc_clk_mhz         noc_axi_clk_mhz     _to_int
    noc_axi_clk_mhz     noc_axi_clk_mhz     _to_int
    clock_mhz           noc_axi_clk_mhz     _to_int
    clock_domain_mhz    noc_axi_clk_mhz     _to_int
    bram_data_width     bram_data_width     _to_int
    endpoint_data_width_bits bram_data_width _to_int
    qos_read_bw_MBps    qos_read_bw         _to_int
    read_qos_MBps       qos_read_bw         _to_int
    qos_write_bw_MBps   qos_write_bw        _to_int
    write_qos_MBps      qos_write_bw        _to_int
    qos_avg_burst       qos_avg_burst       _to_int
    avg_burst           qos_avg_burst       _to_int
    qos_burst           qos_avg_burst       _to_int
    data_width_bits     tg_axi_data_width_bits _to_int
    tg_axi_data_width_bits tg_axi_data_width_bits _to_int
    axi_data_width_bits    tg_axi_data_width_bits _to_int
    sim_runtime         sim_runtime            _to_string
    vivado_sim_runtime  sim_runtime            _to_string
    vivado_wave_csv     vivado_wave_csv        _to_string
    vivado_wave_nps     vivado_wave_nps        _to_string
    vivado_wave_signals vivado_wave_signals    _to_string
    vivado_wave_start   vivado_wave_start      _to_string
    vivado_wave_end     vivado_wave_end        _to_string
    vivado_wave_step    vivado_wave_step       _to_string
    vivado_wave_out     vivado_wave_out        _to_string
    vivado_wave_max_objects vivado_wave_max_objects _to_int
  } {
    if {[dict exists $row $csvk]} {
      set v [${coerce} [dict get $row $csvk]]
      if {$v ne ""} { dict set topo $pk $v }
    }
  }
  return $topo
}

# Build a stable "topology key" for grouping / change detection
proc _topo_key_from_P {P} {
  set mm_tg  [expr {[dict exists $P num_aximm_tg] ? [dict get $P num_aximm_tg] : 0}]
  set mm_bram [expr {[dict exists $P num_aximm_bram] ? [dict get $P num_aximm_bram] : 0}]
  set axis_tg [expr {[dict exists $P num_axis_tg] ? [dict get $P num_axis_tg] : 0}]
  set axis_end [expr {[dict exists $P num_axis_end] ? [dict get $P num_axis_end] : 0}]

  return [format "mm_tg=%s_bram=%s_axis_tg=%s_end=%s" \
    $mm_tg $mm_bram $axis_tg $axis_end]
}

proc _clean_json_label {path} {
    set fname [file tail $path]
    foreach suffix {.conn.json .place.json .json} {
        if {[string match "*$suffix" $fname]} {
            return [string range $fname 0 [expr {[string length $fname] - [string length $suffix] - 1}]]
        }
    }
    return [file rootname $fname]
}

# Detect JSON topology in a row (inline JSON or file path). Returns dict or "".
proc _json_from_row {row} {
    foreach key {connections_json topology_json topology topology_file connection_json connection_file} {
        if {![dict exists $row $key]} { continue }
        set v [string trim [dict get $row $key]]
        if {$v eq ""} { continue }
        set topo  [_parse_topology_from_json $v]
        set label [_clean_json_label $v]
        return [dict create present 1 kind file topo $topo label $label path $v]

    }
    return ""
}

# Detect placement JSON in a row. Returns placement dict or empty dict.
proc _placement_from_row {row} {
    foreach key {placement_json placement placement_file} {
        if {![dict exists $row $key]} { continue }
        set v [string trim [dict get $row $key]]
        if {$v eq ""} { continue }
        return [_parse_placement_json $v]
    }
    return {}
}

# Detect sim_mode in a row. Returns "tlm" or "" (empty = default RTL)
proc _sim_mode_from_row {row} {
    foreach key {sim_mode simulation_mode} {
        if {![dict exists $row $key]} { continue }
        set v [string tolower [string trim [dict get $row $key]]]
        if {$v eq "tlm" || $v eq "systemc" || $v eq "sc"} {
            return "tlm"
        }
    }
    return ""
}

# Extract placement label from a row (filename without extension)
proc _placement_label_from_row {row} {
    foreach key {placement_json placement placement_file} {
        if {![dict exists $row $key]} { continue }
        set v [string trim [dict get $row $key]]
        if {$v eq ""} { continue }
        return [_clean_json_label $v]
    }
    return ""
}

proc _resolve_row_topology {row P} {
    set J [_json_from_row $row]
    set placement [_placement_from_row $row]
    set pl_label [_placement_label_from_row $row]
    set sim_mode [_sim_mode_from_row $row]

    # Merge only recognized topology/project overrides into P.
    set row_overrides [_topology_from_row $row]
    if {[dict exists $row_overrides sim_runtime]} {
        puts "INFO: Row sim_runtime override = [dict get $row_overrides sim_runtime]"
    }
    set Prow [_P_with_topology $P $row_overrides]
    
    set base_key ""
    set topo ""

    if {$J ne "" && [dict get $J present]} {
        # JSON wins for topology structure
        set base_key [dict get $J label]
        set topo [dict get $J topo]
    } else {
        # Build default all-to-all from counts merged into P
        set base_key [_topo_key_from_P $Prow]
        set topo [_default_topology_dict_from_P $Prow]
    }

    if {$pl_label ne ""} {
        set key "${base_key}__${pl_label}"
    } else {
        set key $base_key
    }

    return [dict create Prow $Prow key $key topo $topo placement $placement sim_mode $sim_mode]
}


# Merge overrides into a copy of P
proc _P_with_topology {P topo_overrides} {
  set P2 $P
  foreach {k v} $topo_overrides { dict set P2 $k $v }
  return $P2
}



# ===================== Sweep from CSV ==============
proc sweep_from_csv {P TG_DEFAULTS csv_path {results_csv ""}} {
  _ensure_project $P

  set rows [_csv_read_rows $csv_path]
  if {[llength $rows] == 0} { error "CSV is empty: $csv_path" }

  puts "INFO: Validating test plan..."
  # set required_keys {num_axi_tg}
  set row_num 1
  foreach row $rows {
    incr row_num
    # foreach key $required_keys {
    #   if {![dict exists $row $key] || [dict get $row $key] eq ""} {
    #     error "ERROR: Test plan validation failed. Row $row_num is missing required parameter '$key'."
    #   }
    # }
    # Get the list index (0-based)
    set row_idx [expr {$row_num - 2}]
    # Create an updated dictionary that includes the row number
    set updated_row [dict merge $row [dict create __row_index $row_num]]
    # Use 'lset' to replace the old dictionary in the list with the updated one
    lset rows $row_idx $updated_row
  }
  set cur_key ""
  set cur_P ""
  foreach row $rows {
    _run_test_from_row $row $P $TG_DEFAULTS $results_csv
  }
  catch {close_project}
}

proc run_single_row_from_csv {P TG_DEFAULTS csv_path row_index {results_csv ""}} {
  _ensure_project $P

  # --- Read the CSV and select the specified row ---
  set rows [_csv_read_rows $csv_path]
  # Tcl lists are 0-indexed, but humans think of rows starting at 1 (after the header)
  # The row number from the CSV file corresponds to index (row_index - 1)
  set row_idx [expr {$row_index - 1}]

  if {$row_idx < 0 || $row_idx >= [llength $rows]} {
    error "ERROR: Invalid row_index '$row_index'. File has [llength $rows] data rows."
  }
  set row [lindex $rows $row_idx]
  # Add the index for logging purposes
  dict set row __row_index [expr {$row_idx + 1}]
  set cur_key ""
  set cur_P ""
  _run_test_from_row $row $P $TG_DEFAULTS $results_csv
  catch {close_project}
}

proc _run_test_from_row {row P TG_DEFAULTS results_csv} {
  upvar cur_key cur_key
  upvar cur_P cur_P

  # --- Build the topology for this single row ---
  set R    [_resolve_row_topology $row $P]
  set Prow [dict get $R Prow]
  set key  [dict get $R key]
  set topo [dict get $R topo]
  set placement [dict get $R placement]
  set sim_mode [dict get $R sim_mode]

  if {$key ne $cur_key} {
    set cur_key $key
    set cur_P   $Prow
    puts "==== Building BD: key=$key ===="
    # _build_bd_from_params $cur_P
    _build_bd_from_topology $cur_P $topo $placement $sim_mode

    set out_dir [file normalize [file join $::SWEEP_ROOT "artifacts" "noc_desc" $::RESULTS_TAG $key]]
    collect_noc_descriptors $cur_P $out_dir $key
  }

  # --- Run the simulation for this row  ---
  set combo [dict merge $TG_DEFAULTS [_prepare_tg_config_from_row $row]]
  set combo [_finalize_vivado_tg_config $combo $Prow]

  set tg_cell_overrides [_prepare_tg_cell_overrides_from_row $row]
  set changed_cells [_set_user_tg_props_delta $combo $tg_cell_overrides]
  if {[llength $changed_cells] > 0} {
    puts "INFO: TG properties changed. Regenerating simulation targets..."
    save_bd_design
    set top_bd_file [get_files [dict get $cur_P bd_name].bd]
    if {$top_bd_file ne ""} {
      generate_target simulation $top_bd_file
    }
  }

  set tg_mode [string tolower [string trim [_dget $row tg_mode ""]]]

  set row_label [_dget $row name ""]
  set Psim [dict merge $cur_P $Prow]
  dict set Psim vivado_wave_label $row_label

  set start_time [clock seconds]
  _run_sim $Psim
  set end_time [clock seconds]
  set sim_duration_s [expr {$end_time - $start_time}]

  collect_sim_results_to_csv $Psim $combo $row_label $results_csv $sim_duration_s
  _copy_sim_log $Psim $row_label

}

# ======================== TOPOLOGY-ONLY GENERATION ============================
# Build block designs and export NCR/NTS files without running simulation.
# Useful for generating topology files for gem5 simulation.

proc generate_topology_from_csv {P csv_path} {
  _ensure_project $P

  set rows [_csv_read_rows $csv_path]
  if {[llength $rows] == 0} { error "CSV is empty: $csv_path" }

  puts "INFO: Generating topologies from [llength $rows] rows..."
  
  set cur_key ""
  set cur_P ""
  set topology_count 0

  foreach row $rows {
    _build_topology_from_row $row $P cur_key cur_P topology_count
  }

  puts "INFO: Generated $topology_count unique topologies."
  catch {close_project}
}

proc _build_topology_from_row {row P cur_key_var cur_P_var count_var} {
  upvar 1 $cur_key_var cur_key
  upvar 1 $cur_P_var cur_P
  upvar 1 $count_var topology_count

  # --- Build the topology for this single row ---
  set R    [_resolve_row_topology $row $P]
  set Prow [dict get $R Prow]
  set key  [dict get $R key]
  set topo [dict get $R topo]
  set placement [dict get $R placement]
  set sim_mode [dict get $R sim_mode]

  # Only build if topology is different from the previous row
  if {$key ne $cur_key} {
    set cur_key $key
    set cur_P   $Prow
    puts "==== Building Topology: key=$key ===="

    # Build the block design
    _build_bd_from_topology $cur_P $topo $placement $sim_mode

    # Export NCR/NTS files
    set out_dir [file normalize [file join $::SWEEP_ROOT "artifacts" "noc_desc" $::RESULTS_TAG $key]]
    collect_noc_descriptors $cur_P $out_dir $key

    incr topology_count
    puts "INFO: Topology $key exported to $out_dir"
  } else {
    puts "INFO: Skipping row - topology $key already generated"
  }
}

# ======================== SINGLE ROW TOPOLOGY GENERATION =======================
# Build block design and export NCR/NTS for a single row (by 1-based index).

proc generate_topology_for_row {P csv_path row_index} {
  _ensure_project $P

  set rows [_csv_read_rows $csv_path]
  if {[llength $rows] == 0} { error "CSV is empty: $csv_path" }
  
  set row_idx [expr {int($row_index) - 1}]
  if {$row_idx < 0 || $row_idx >= [llength $rows]} {
    error "Row index $row_index out of range (1-[llength $rows])"
  }

  set row [lindex $rows $row_idx]
  puts "INFO: Generating topology for row $row_index..."
  
  # Dummy variables for tracking (not used for single row)
  set cur_key ""
  set cur_P ""
  set topology_count 0

  _build_topology_from_row $row $P cur_key cur_P topology_count

  puts "INFO: Topology generation complete for row $row_index."
  catch {close_project}
}
