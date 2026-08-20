proc _ensure_project {P} {
  set project_name [dict get $P project_name]
  set project_dir  [dict get $P project_dir]
  set part         [dict get $P part]
  set board_part   [dict get $P board_part]
  if {[catch {current_project} _]} {
    create_project -force $project_name $project_dir -part $part
    if {$board_part ne ""} { catch {set_property board_part $board_part [current_project]} }
  }
}

proc _truthy {v} {
  set s [string tolower [string trim $v]]
  return [expr {$s in {1 true yes on y enable enabled}}]
}

proc _csv_quote {s} {
  set s [string map {"\"" "\"\""} $s]
  return "\"$s\""
}

proc _split_csv_terms {s} {
  set s [string map {";" "," "|" ","} $s]
  set out {}
  foreach item [split $s ","] {
    set item [string trim $item]
    if {$item ne ""} { lappend out $item }
  }
  return $out
}

proc _matches_any_term {text terms} {
  if {[llength $terms] == 0} { return 1 }
  set lower [string tolower $text]
  foreach term $terms {
    set needle [string tolower [string trim $term]]
    if {$needle eq "*"} { return 1 }
    if {$needle ne "" && [string first $needle $lower] >= 0} {
      return 1
    }
  }
  return 0
}

proc _sanitize_artifact_label {s} {
  set s [string trim $s]
  if {$s eq ""} { set s "unnamed" }
  return [string map {" " "_" "," "_" ":" "_" "/" "_" "\\" "_" "[" "_" "]" "_"} $s]
}

proc _time_to_ps {time_str} {
  set s [string trim $time_str]
  if {$s eq ""} { return "" }
  if {![regexp -nocase {^([0-9]+(?:\.[0-9]+)?)\s*([a-z]+)?$} $s -> value unit]} {
    error "Could not parse time value '$time_str'"
  }
  set unit [string tolower $unit]
  if {$unit eq ""} { set unit "ns" }
  switch -- $unit {
    fs { set scale 0.001 }
    ps { set scale 1 }
    ns { set scale 1000 }
    us { set scale 1000000 }
    ms { set scale 1000000000 }
    s -
    sec { set scale 1000000000000 }
    default { error "Unsupported time unit '$unit' in '$time_str'" }
  }
  return [expr {int(round(double($value) * $scale))}]
}

proc _ps_to_run_args {ps} {
  return [list $ps ps]
}

proc _wave_cfg_get {P key default} {
  if {[dict exists $P $key]} {
    set v [string trim [dict get $P $key]]
    if {$v ne ""} { return $v }
  }
  set env_key [string toupper $key]
  if {[info exists ::env($env_key)] && [string trim $::env($env_key)] ne ""} {
    return [string trim $::env($env_key)]
  }
  return $default
}

proc _wave_csv_enabled {P} {
  set v [_wave_cfg_get $P vivado_wave_csv 0]
  return [_truthy $v]
}

proc _wave_csv_path {P} {
  set explicit [_wave_cfg_get $P vivado_wave_out ""]
  if {$explicit ne ""} { return [file normalize $explicit] }

  set tag [expr {[info exists ::RESULTS_TAG] ? $::RESULTS_TAG : [clock format [clock seconds] -format "%Y%m%d_%H%M%S"]}]
  set outdir [file join $::SWEEP_ROOT "artifacts" "vivado_wave_csv" $tag]
  file mkdir $outdir
  set label [_sanitize_artifact_label [_wave_cfg_get $P vivado_wave_label "wave"]]
  return [file join $outdir "${label}.csv"]
}

proc _wave_signal_name {obj signal_terms} {
  set lower [string tolower $obj]
  foreach term $signal_terms {
    set t [string tolower [string trim $term]]
    if {$t ne "" && [string first $t $lower] >= 0} { return [string trim $term] }
  }
  return [file tail $obj]
}

proc _wave_nps_name {obj nps_terms} {
  set lower [string tolower $obj]
  foreach term $nps_terms {
    set t [string tolower [string trim $term]]
    if {$t ne "" && [string first $t $lower] >= 0} { return [string trim $term] }
  }
  return ""
}

proc _wave_route_nps_order_from_ncr {P} {
  set out {}
  if {![dict exists $P project_dir] || ![dict exists $P project_name] || ![dict exists $P bd_name]} {
    return $out
  }
  set ncr [file normalize [file join [dict get $P project_dir] \
    "[dict get $P project_name].gen" sources_1 bd [dict get $P bd_name] nsln \
    "[dict get $P bd_name].ncr"]]
  if {![file exists $ncr]} { return $out }

  package require json
  set fh [open $ncr r]
  set txt [read $fh]
  close $fh
  set data [json::json2dict $txt]
  if {![dict exists $data Paths]} { return $out }

  set seen [dict create]
  foreach path [dict get $data Paths] {
    if {![dict exists $path Nets]} { continue }
    foreach net [dict get $path Nets] {
      if {![dict exists $net Connections]} { continue }
      foreach item [dict get $net Connections] {
        if {[string match "NOC_NPS*" $item] && ![dict exists $seen $item]} {
          dict set seen $item 1
          lappend out $item
        }
      }
    }
  }
  return $out
}

proc _wave_expand_nps_terms {P nps_terms} {
  set terms $nps_terms
  set display [dict create]
  foreach term $nps_terms {
    set t [string trim $term]
    if {$t ne ""} { dict set display [string tolower $t] $t }
  }

  set active_nps [_wave_route_nps_order_from_ncr $P]
  foreach term $nps_terms {
    set t [string trim $term]
    if {$t eq "" || $t eq "*"} { continue }
    for {set i 0} {$i < [llength $active_nps]} {incr i} {
      set logical [lindex $active_nps $i]
      if {[string equal -nocase $t $logical]} {
        foreach alias [list "nps_${i}" "xlnoc_nps_${i}_0"] {
          lappend terms $alias
          dict set display [string tolower $alias] $logical
        }
        puts "INFO: Vivado wave NPS alias: $logical -> nps_${i} / xlnoc_nps_${i}_0"
        break
      }
    }
  }
  return [dict create terms [lsort -unique $terms] display $display]
}

proc _wave_display_nps_name {obj display_map nps_terms} {
  set lower [string tolower $obj]
  foreach key [dict keys $display_map] {
    if {[string first $key $lower] >= 0} {
      return [dict get $display_map $key]
    }
  }
  return [_wave_nps_name $obj $nps_terms]
}

proc _wave_port_channel {obj} {
  set parts [split $obj "/"]
  set hints {}
  foreach p $parts {
    if {[regexp -nocase {(port|chan|channel|vc|queue|aw|w|b|ar|r)[A-Za-z0-9_]*} $p]} {
      lappend hints $p
    }
  }
  if {[llength $hints] == 0} { return "" }
  return [join $hints "/"]
}

proc _wave_find_objects {nps_terms signal_terms max_objects} {
  set matches {}
  set inventory {}
  set all_objects [get_objects -r /*]
  foreach obj $all_objects {
    set obj_s $obj
    if {[catch {get_property NAME $obj} obj_name] == 0 && $obj_name ne ""} {
      set obj_s $obj_name
    }
    if {[_matches_any_term $obj_s $nps_terms]} {
      lappend inventory $obj_s
      if {[_matches_any_term $obj_s $signal_terms]} {
        lappend matches $obj_s
        if {$max_objects > 0 && [llength $matches] >= $max_objects} {
          break
        }
      }
    }
  }
  return [dict create matches [lsort -unique $matches] inventory [lsort -unique $inventory]]
}

proc _wave_write_inventory {out_path inventory} {
  set inv "${out_path}.inventory"
  set fh [open $inv w]
  foreach obj $inventory { puts $fh $obj }
  close $fh
  puts "INFO: Wrote Vivado waveform object inventory to $inv"
}

proc _write_wave_sampler_tcl {script_path out_path nps_terms nps_display signal_terms max_objects start_ps end_ps step_ps} {
  file mkdir [file dirname $script_path]
  file mkdir [file dirname $out_path]
  set fh [open $script_path w]
  puts $fh [list set out_path $out_path]
  puts $fh [list set nps_terms $nps_terms]
  puts $fh [list set nps_display $nps_display]
  puts $fh [list set signal_terms $signal_terms]
  puts $fh [list set max_objects $max_objects]
  puts $fh [list set start_ps $start_ps]
  puts $fh [list set end_ps $end_ps]
  puts $fh [list set step_ps $step_ps]
  puts $fh {
proc _csv_quote {s} {
  set s [string map {"\"" "\"\""} $s]
  return "\"$s\""
}
proc _matches_any_term {text terms} {
  if {[llength $terms] == 0} { return 1 }
  set lower [string tolower $text]
  foreach term $terms {
    set needle [string tolower [string trim $term]]
    if {$needle eq "*"} { return 1 }
    if {$needle ne "" && [string first $needle $lower] >= 0} { return 1 }
  }
  return 0
}
proc _wave_signal_name {obj signal_terms} {
  set lower [string tolower $obj]
  foreach term $signal_terms {
    set t [string tolower [string trim $term]]
    if {$t ne "" && [string first $t $lower] >= 0} { return [string trim $term] }
  }
  return [file tail $obj]
}
proc _wave_display_nps_name {obj display_map nps_terms} {
  set lower [string tolower $obj]
  foreach key [dict keys $display_map] {
    if {[string first $key $lower] >= 0} { return [dict get $display_map $key] }
  }
  foreach term $nps_terms {
    set t [string tolower [string trim $term]]
    if {$t ne "" && [string first $t $lower] >= 0} { return [string trim $term] }
  }
  return ""
}
proc _wave_port_channel {obj} {
  set parts [split $obj "/"]
  set hints {}
  foreach p $parts {
    if {[regexp -nocase {(port|chan|channel|vc|queue|aw|w|b|ar|r)[A-Za-z0-9_]*} $p]} {
      lappend hints $p
    }
  }
  if {[llength $hints] == 0} { return "" }
  return [join $hints "/"]
}
proc _wave_get_value {obj} {
  if {[catch {get_value -radix unsigned $obj} value]} {
    if {[catch {get_value $obj} value2]} { return "" }
    return $value2
  }
  return $value
}
proc _wave_find_objects {nps_terms signal_terms max_objects} {
  set matches {}
  set inventory {}
  set all_objects [get_objects -r /*]
  foreach obj $all_objects {
    set obj_s $obj
    if {[catch {get_property NAME $obj} obj_name] == 0 && $obj_name ne ""} {
      set obj_s $obj_name
    }
    if {[_matches_any_term $obj_s $nps_terms]} {
      lappend inventory $obj_s
      if {[_matches_any_term $obj_s $signal_terms]} {
        lappend matches $obj_s
        if {$max_objects > 0 && [llength $matches] >= $max_objects} { break }
      }
    }
  }
  return [dict create matches [lsort -unique $matches] inventory [lsort -unique $inventory]]
}
proc _write_sample {fh objects nps_terms nps_display signal_terms} {
  set now [current_time -s]
  foreach obj $objects {
    set value [_wave_get_value $obj]
    puts $fh "[_csv_quote $now],[_csv_quote [_wave_display_nps_name $obj $nps_display $nps_terms]],[_csv_quote [_wave_port_channel $obj]],[_csv_quote [_wave_signal_name $obj $signal_terms]],[_csv_quote $value],[_csv_quote $obj]"
  }
}

set found [_wave_find_objects $nps_terms $signal_terms $max_objects]
set objects [dict get $found matches]
set inv "${out_path}.inventory"
set inv_fh [open $inv w]
foreach obj [dict get $found inventory] { puts $inv_fh $obj }
close $inv_fh

set csv_fh [open $out_path w]
puts $csv_fh "time,nps_name,port_channel,signal,value,object"
if {[llength $objects] == 0} {
  puts "WARN: Vivado wave CSV enabled, but no matching HDL objects were found. CSV has header only: $out_path"
  close $csv_fh
  if {$end_ps > 0} { run $end_ps ps }
  quit
}

puts "INFO: Vivado wave CSV sampling [llength $objects] object(s) to $out_path"
if {$start_ps > 0} { run $start_ps ps }
_write_sample $csv_fh $objects $nps_terms $nps_display $signal_terms

set now_ps $start_ps
while {$now_ps < $end_ps} {
  set delta [expr {$end_ps - $now_ps}]
  if {$delta > $step_ps} { set delta $step_ps }
  run $delta ps
  set now_ps [expr {$now_ps + $delta}]
  _write_sample $csv_fh $objects $nps_terms $nps_display $signal_terms
}
close $csv_fh
puts "INFO: Wrote Vivado waveform CSV to $out_path"
quit
}
  close $fh
  puts "INFO: Wrote Vivado wave sampler Tcl to $script_path"
}

proc _run_sim_with_wave_csv {P fs sim_runtime} {
  set start_ps [_time_to_ps [_wave_cfg_get $P vivado_wave_start "0 ns"]]
  set end_ps [_time_to_ps [_wave_cfg_get $P vivado_wave_end $sim_runtime]]
  set step_ps [_time_to_ps [_wave_cfg_get $P vivado_wave_step "1 ns"]]
  if {$end_ps eq "" || $end_ps <= 0} { error "Vivado wave CSV end time must be > 0" }
  if {$step_ps eq "" || $step_ps <= 0} { error "Vivado wave CSV step time must be > 0" }
  if {$start_ps eq "" || $start_ps < 0} { set start_ps 0 }
  if {$start_ps > $end_ps} { error "Vivado wave CSV start time is after end time" }

  set nps_cfg_terms [_split_csv_terms [_wave_cfg_get $P vivado_wave_nps "NOC_NPS_VNOC_X1Y0,NOC_NPS7575_X5Y0"]]
  set nps_info [_wave_expand_nps_terms $P $nps_cfg_terms]
  set nps_terms [dict get $nps_info terms]
  set nps_display [dict get $nps_info display]
  set signal_terms [_split_csv_terms [_wave_cfg_get $P vivado_wave_signals "ready,valid,grant,queue,depth,aw,w,b,ar,r"]]
  set max_objects [_wave_cfg_get $P vivado_wave_max_objects 256]
  if {![string is integer -strict $max_objects]} { set max_objects 256 }

  set out_path [_wave_csv_path $P]
  set script_path "${out_path}.xsim.tcl"
  _write_wave_sampler_tcl $script_path $out_path $nps_terms $nps_display $signal_terms $max_objects $start_ps $end_ps $step_ps

  set_property xsim.simulate.runtime "0 ns" $fs
  set_property xsim.simulate.log_all_signals false $fs
  set_property xsim.simulate.custom_tcl $script_path $fs
  launch_simulation
  return $out_path
}

proc _run_sim {P} {
  catch {close_sim}
  update_compile_order -fileset sim_1
  set fs [get_filesets sim_1]

  # Keep things light: no giant wave DB, no log-all-signals !!!!!!!!! uncomment these to make sim faster
#   set_property xsim.elaborate.debug_level off $fs
#   set_property xsim.simulate.log_all_signals false $fs
#   set_property xsim.simulate.wdb {} $fs
  set_property xsim.elaborate.debug_level typical $fs

  # Run using only launch_simulation
  update_compile_order -fileset sources_1
  set sim_runtime "100s"
  if {[dict exists $P sim_runtime]} {
    set row_sim_runtime [string trim [dict get $P sim_runtime]]
    if {$row_sim_runtime ne ""} {
      set sim_runtime $row_sim_runtime
    }
  }
  puts "INFO: XSim runtime = $sim_runtime"
  if {[_wave_csv_enabled $P]} {
    _run_sim_with_wave_csv $P $fs $sim_runtime
  } else {
    set_property xsim.simulate.custom_tcl {} $fs
    set_property xsim.simulate.log_all_signals false $fs
    set_property xsim.simulate.runtime $sim_runtime $fs
    launch_simulation
  }
  catch {close_sim}
}

proc _recreate_bd {bd_name} {
    catch {close_bd_design -quiet $bd_name}
    set bdfile [get_files -quiet */bd/$bd_name/${bd_name}.bd]
    if {$bdfile ne ""} { catch {remove_files $bdfile} }
    create_bd_design $bd_name
    current_bd_design $bd_name
}

proc _create_common_components {axi_clk num_tg} {
    # create common components
    create_bd_cell -type ip -vlnv xilinx.com:ip:clk_gen_sim:1.0 noc_clk_gen
    create_bd_cell -type ip -vlnv xilinx.com:ip:sim_trig:1.0 noc_sim_trig
    set_property CONFIG.USER_AXI_CLK_0_FREQ $axi_clk [get_bd_cells noc_clk_gen]
    set_property CONFIG.USER_NUM_AXI_TG $num_tg [get_bd_cells noc_sim_trig]
    # connect common signals
    make_bd_pins_external  [get_bd_pins noc_clk_gen/axi_clk_in_0]
    make_bd_pins_external  [get_bd_pins noc_clk_gen/axi_rst_in_0_n]
    connect_bd_net [get_bd_pins noc_clk_gen/axi_clk_0] [get_bd_pins noc_sim_trig/pclk]
    connect_bd_net [get_bd_pins noc_clk_gen/axi_rst_0_n] [get_bd_pins noc_sim_trig/rst_n]
}

proc _create_aximm_tg {tg_name monitor_name i tg_width_bits} {
    set noc_si_pin    [format "S%02d_AXI" $i]
    create_bd_cell -type ip -vlnv xilinx.com:ip:perf_axi_tg:1.0 $tg_name
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_pmon:1.0 $monitor_name
    set_property CONFIG.USER_PARAM_AXI_TG_ID $i [get_bd_cells $monitor_name]

    set trig_out_pin [format "trig_%02d" $i]
    set all_done_pin [format "all_done_%02d" $i]

    connect_bd_net [get_bd_pins noc_sim_trig/$trig_out_pin]     [get_bd_pins $tg_name/axi_tg_start]
    connect_bd_net [get_bd_pins $tg_name/axi_tg_done]           [get_bd_pins noc_sim_trig/$all_done_pin]
    connect_bd_net [get_bd_pins noc_sim_trig/ph_trig_out]       [get_bd_pins $tg_name/trigger_in]

    # Connect to noc and pmon
    connect_bd_intf_net [get_bd_intf_pins $tg_name/M_AXI]   [get_bd_intf_pins axi_noc_0/$noc_si_pin]
    connect_bd_intf_net [get_bd_intf_pins $tg_name/M_AXI]   [get_bd_intf_pins $monitor_name/S_AXI]

    set_property CONFIG.USER_C_AXI_WDATA_WIDTH $tg_width_bits [get_bd_cells $tg_name]
    # Clock/reset
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_clk_0]    [get_bd_pins $tg_name/clk]
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_rst_0_n]  [get_bd_pins $tg_name/tg_rst_n]
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_clk_0]    [get_bd_pins $monitor_name/axi_aclk]
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_rst_0_n]  [get_bd_pins $monitor_name/axi_arst_n]
}

proc _dict_first_present {d keys} {
    foreach k $keys {
        if {[dict exists $d $k]} {
            set v [string trim [dict get $d $k]]
            if {$v ne ""} { return $v }
        }
    }
    return ""
}

proc _tg_master_addr_value {md keys} {
    if {[dict exists $md params]} {
        set v [_dict_first_present [dict get $md params] $keys]
        if {$v ne ""} { return $v }
    }
    if {[dict exists $md port_config]} {
        set v [_dict_first_present [dict get $md port_config] $keys]
        if {$v ne ""} { return $v }
    }
    return ""
}

proc _set_tg_axi_addr_pair {tg_name channel base high} {
    if {$base eq ""} { return }

    set cell [get_bd_cells -quiet $tg_name]
    if {$cell eq ""} { return }

    set base_prop "CONFIG.USER_C_AXI_${channel}_BASEADDR"
    set high_prop "CONFIG.USER_C_AXI_${channel}_HIGHADDR"
    if {[catch {get_property $base_prop $cell}]} {
        return
    }

    set mode_dict [list "${base_prop}.VALUE_MODE" MANUAL]
    if {![catch {get_property $high_prop $cell}]} {
        if {$high eq ""} {
            lappend mode_dict "${high_prop}.VALUE_MODE" AUTO
        } else {
            lappend mode_dict "${high_prop}.VALUE_MODE" MANUAL
        }
    }
    catch {set_property -dict $mode_dict $cell}

    set_property $base_prop $base $cell
    if {$high ne "" && ![catch {get_property $high_prop $cell}]} {
        set_property $high_prop $high $cell
    }

    set range_msg $base
    if {$high ne ""} { set range_msg "${base}..${high}" }
    puts "INFO: Set $tg_name $channel address range to $range_msg"
}

proc _apply_aximm_tg_address_config {tg_name md} {
    set write_base [_tg_master_addr_value $md {USER_C_AXI_WRITE_BASEADDR write_base_addr write_base_address base_addr base_address}]
    set write_high [_tg_master_addr_value $md {USER_C_AXI_WRITE_HIGHADDR write_high_addr write_high_address high_addr high_address max_addr max_address}]
    set read_base  [_tg_master_addr_value $md {USER_C_AXI_READ_BASEADDR read_base_addr read_base_address}]
    set read_high  [_tg_master_addr_value $md {USER_C_AXI_READ_HIGHADDR read_high_addr read_high_address}]

    if {$read_base eq ""} { set read_base $write_base }
    if {$read_high eq ""} { set read_high $write_high }

    _set_tg_axi_addr_pair $tg_name WRITE $write_base $write_high
    _set_tg_axi_addr_pair $tg_name READ $read_base $read_high
}

proc _create_hbm_tg {tg_name monitor_name hbm_idx tg_width_bits global_tg_idx} {
    # HBM uses HBMxx_AXI naming instead of Sxx_AXI
    set noc_si_pin [format "HBM%02d_AXI" $hbm_idx]
    create_bd_cell -type ip -vlnv xilinx.com:ip:perf_axi_tg:1.0 $tg_name
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_pmon:1.0 $monitor_name
    set_property CONFIG.USER_PARAM_AXI_TG_ID $global_tg_idx [get_bd_cells $monitor_name]
    set trig_out_pin [format "trig_%02d" $global_tg_idx]
    set all_done_pin [format "all_done_%02d" $global_tg_idx]
    connect_bd_net [get_bd_pins noc_sim_trig/$trig_out_pin]     [get_bd_pins $tg_name/axi_tg_start]
    connect_bd_net [get_bd_pins $tg_name/axi_tg_done]           [get_bd_pins noc_sim_trig/$all_done_pin]
    connect_bd_net [get_bd_pins noc_sim_trig/ph_trig_out]       [get_bd_pins $tg_name/trigger_in]
    # Connect to HBM interface on NoC
    connect_bd_intf_net [get_bd_intf_pins $tg_name/M_AXI]   [get_bd_intf_pins axi_noc_0/$noc_si_pin]
    connect_bd_intf_net [get_bd_intf_pins $tg_name/M_AXI]   [get_bd_intf_pins $monitor_name/S_AXI]
    set_property CONFIG.USER_C_AXI_WDATA_WIDTH $tg_width_bits [get_bd_cells $tg_name]
    # Clock/reset
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_clk_0]    [get_bd_pins $tg_name/clk]
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_rst_0_n]  [get_bd_pins $tg_name/tg_rst_n]
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_clk_0]    [get_bd_pins $monitor_name/axi_aclk]
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_rst_0_n]  [get_bd_pins $monitor_name/axi_arst_n]

    set_property CONFIG.USER_C_AXI_WID_WIDTH {7} [get_bd_cells $tg_name]
}

proc _create_axis_tg {P tg_name i tg_width_bits offset num_packets} {
    # puts "what i is $i what offset is $offset"
    set noc_si_pin    [format "S%02d_AXIS" $i]
    set trig_out_pin [format "trig_%02d" [expr {$i + $offset}]]
    set all_done_pin [format "all_done_%02d" [expr {$i + $offset}]]
    create_bd_cell -type ip -vlnv xilinx.com:ip:perf_axi_tg:1.0 $tg_name

    set_property CONFIG.USER_C_AXI_PROTOCOL {AXI4_STREAM} [get_bd_cells $tg_name]
    set_property CONFIG.USER_C_AXIS_TDATA_WIDTH $tg_width_bits [get_bd_cells $tg_name]
    set_property CONFIG.USER_C_AXIS_NO_OF_PKT $num_packets [get_bd_cells $tg_name]
    if {[dict exists $P USER_C_AXIS_PKT_LEN]} {
        set pkt_len [dict get $P USER_C_AXIS_PKT_LEN]
        puts "INFO: Setting AXIS packet length to $pkt_len for $tg_name"
        set_property CONFIG.USER_C_AXIS_PKT_LEN $pkt_len [get_bd_cells $tg_name]
    }

    connect_bd_intf_net [get_bd_intf_pins $tg_name/M_AXIS]     [get_bd_intf_pins axis_noc_0/$noc_si_pin]
    connect_bd_net [get_bd_pins noc_clk_gen/axi_clk_0]   [get_bd_pins $tg_name/clk]
    connect_bd_net [get_bd_pins noc_clk_gen/axi_rst_0_n] [get_bd_pins $tg_name/tg_rst_n]

    connect_bd_net [get_bd_pins noc_sim_trig/$trig_out_pin]         [get_bd_pins $tg_name/axi_tg_start]
    connect_bd_net [get_bd_pins $tg_name/axi_tg_done]           [get_bd_pins noc_sim_trig/$all_done_pin]
    connect_bd_net [get_bd_pins noc_sim_trig/ph_trig_out]             [get_bd_pins $tg_name/trigger_in]

}

proc _create_bram_endpoint {bram_ctrl_name bram_mem_name i bram_width_bits} {
    set noc_mi_pin    [format "M%02d_AXI" $i]
    # Create bram ips
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_bram_ctrl:4.1 $bram_ctrl_name
    create_bd_cell -type ip -vlnv xilinx.com:ip:emb_mem_gen:1.0 $bram_mem_name
    # Set bram ip params
    set_property -dict [list \
        CONFIG.MEMORY_DEPTH {1024} \
        CONFIG.MEMORY_TYPE {True_Dual_Port_RAM} \
    ] [get_bd_cells $bram_mem_name]
    set_property CONFIG.DATA_WIDTH $bram_width_bits [get_bd_cells $bram_ctrl_name]
    # Connect bram ports
    connect_bd_intf_net [get_bd_intf_pins $bram_mem_name/BRAM_PORTA] [get_bd_intf_pins $bram_ctrl_name/BRAM_PORTA]
    connect_bd_intf_net [get_bd_intf_pins $bram_mem_name/BRAM_PORTB] [get_bd_intf_pins $bram_ctrl_name/BRAM_PORTB]
    connect_bd_intf_net [get_bd_intf_pins $bram_ctrl_name/S_AXI] [get_bd_intf_pins axi_noc_0/$noc_mi_pin]
    # Clock/reset
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_clk_0]    [get_bd_pins $bram_ctrl_name/s_axi_aclk]
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_rst_0_n]    [get_bd_pins $bram_ctrl_name/s_axi_aresetn]
}

proc _create_axis_endpoint {endpoint_name i data_width_bits} {
    set noc_mi_pin    [format "M%02d_AXIS" $i]
    create_bd_cell -type module -reference axis_endpoint $endpoint_name

    set_property -dict [list \
        CONFIG.DATA_WIDTH $data_width_bits \
        CONFIG.KEEP_WIDTH [expr {$data_width_bits / 8}] \
    ] [get_bd_cells $endpoint_name]
    connect_bd_intf_net [get_bd_intf_pins axis_noc_0/$noc_mi_pin] [get_bd_intf_pins $endpoint_name/S_AXIS]
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_clk_0]    [get_bd_pins $endpoint_name/ACLK]
    connect_bd_net [get_bd_pins /noc_clk_gen/axi_rst_0_n]    [get_bd_pins $endpoint_name/ARESETN]
}

# Create an AXIS data FIFO and connect M_AXIS/S_AXIS to the NoC
# fifo_name: base name for the FIFO IP (e.g., \"axis_fifo_0\")
# m_idx: index for the NoC S-port (FIFO's M_AXIS connects to NoC S-port)
# s_idx: index for the NoC M-port (FIFO's S_AXIS connects to NoC M-port)
proc _create_axis_fifo {fifo_name m_idx s_idx} {
    set noc_si_pin [format "S%02d_AXIS" $m_idx]
    set noc_mi_pin [format "M%02d_AXIS" $s_idx]
    
    # Create the FIFO IP
    create_bd_cell -type ip -vlnv xilinx.com:ip:axis_data_fifo:2.0 $fifo_name
    
    # Use shift register implementation to avoid XPM dependency in simulation
    set_property -dict [list \
        CONFIG.FIFO_IMPL {auto} \
        CONFIG.FIFO_DEPTH {512} \
    ] [get_bd_cells $fifo_name]
    
    # Connect clock and reset
    connect_bd_net [get_bd_pins $fifo_name/s_axis_aclk] [get_bd_pins noc_clk_gen/axi_clk_0]
    connect_bd_net [get_bd_pins $fifo_name/s_axis_aresetn] [get_bd_pins noc_clk_gen/axi_rst_0_n]
    
    # Connect FIFO M_AXIS to NoC S-port (FIFO output -> NoC input)
    connect_bd_intf_net [get_bd_intf_pins $fifo_name/M_AXIS] [get_bd_intf_pins axis_noc_0/$noc_si_pin]
    # Connect NoC M-port to FIFO S_AXIS (NoC output -> FIFO input)
    connect_bd_intf_net [get_bd_intf_pins axis_noc_0/$noc_mi_pin] [get_bd_intf_pins $fifo_name/S_AXIS]
}

# Apply physical placement to NoC endpoints
# Args:
#   placement_dict - Dict with master_placement and slave_placement
#   m_index_arr - Array mapping master names to S-port indices
#   s_index_arr - Array mapping slave names to M-port indices
#   num_aximm_tg - Number of regular AXIMM TGs (for HBM offset)
proc _apply_noc_placements {placement_dict m_index_arr s_index_arr num_aximm_tg} {
    upvar 1 $m_index_arr m_index
    upvar 1 $s_index_arr s_index

    set applied_count 0

    # Apply master placements
    if {[dict exists $placement_dict master_placement]} {
        set master_pl [dict get $placement_dict master_placement]
        foreach mname [dict keys $master_pl] {
            if {![info exists m_index($mname)]} {
                puts "WARN: Placement for unknown master '$mname', skipping"
                continue
            }
            set i $m_index($mname)
            set loc [dict get $master_pl $mname]

            # Determine pin name based on index (HBM vs regular AXIMM)
            if {$i >= $num_aximm_tg} {
                set hbm_idx [expr {$i - $num_aximm_tg}]
                set pin [get_bd_intf_pins axi_noc_0/[format "HBM%02d_AXI" $hbm_idx]]
            } else {
                set pin [get_bd_intf_pins axi_noc_0/[format "S%02d_AXI" $i]]
            }

            puts "INFO: Placing master $mname ($pin) at $loc"
            set_property -dict [list CONFIG.PHYSICAL_LOC $loc] $pin
            incr applied_count
        }
    }

    # Apply slave placements
    if {[dict exists $placement_dict slave_placement]} {
        set slave_pl [dict get $placement_dict slave_placement]
        foreach sname [dict keys $slave_pl] {
            set loc [dict get $slave_pl $sname]
            if {[info exists s_index($sname)]} {
                set j $s_index($sname)
                set pin [get_bd_intf_pins axi_noc_0/[format "M%02d_AXI" $j]]
            } elseif {[regexp {^hbm(\d+)_port(\d+)$} $sname -> ctrl_num port_num]} {
                set pin [get_bd_intf_pins axi_noc_0/[format "HBM%d_PORT%d" $ctrl_num $port_num]]
            } else {
                puts "WARN: Placement for unknown slave '$sname', skipping"
                continue
            }

            puts "INFO: Placing slave $sname ($pin) at $loc"
            set_property -dict [list CONFIG.PHYSICAL_LOC $loc] $pin
            incr applied_count
        }
    }

    # Apply DDR placements (pin names are used directly from JSON)
    if {[dict exists $placement_dict ddr_placement]} {
        set ddr_pl [dict get $placement_dict ddr_placement]
        foreach pin_name [dict keys $ddr_pl] {
            set loc [dict get $ddr_pl $pin_name]
            set pin [get_bd_intf_pins -quiet axi_noc_0/$pin_name]

            if {$pin eq ""} {
                puts "WARN: DDR pin '$pin_name' not found on axi_noc_0, skipping"
                continue
            }

            puts "INFO: Placing DDR $pin_name ($pin) at $loc"
            set_property -dict [list CONFIG.PHYSICAL_LOC $loc] $pin
            incr applied_count
        }
    }

    puts "INFO: Applied $applied_count physical placements"
    return $applied_count
}

# Apply physical placement to AXIS NoC endpoints
# Args:
#   placement_dict - Dict with master_placement and slave_placement
#   m_index_arr - Array mapping master names to S-port indices (on axis_noc_0)
#   s_index_arr - Array mapping slave names to M-port indices (on axis_noc_0)
proc _apply_axis_noc_placements {placement_dict m_index_arr s_index_arr} {
    upvar 1 $m_index_arr m_index
    upvar 1 $s_index_arr s_index

    set applied_count 0

    # Apply master placements (masters connect to S-ports on axis_noc_0)
    if {[dict exists $placement_dict master_placement]} {
        set master_pl [dict get $placement_dict master_placement]
        foreach mname [dict keys $master_pl] {
            if {![info exists m_index($mname)]} {
                puts "WARN: AXIS placement for unknown master '$mname', skipping"
                continue
            }
            set i $m_index($mname)
            set loc [dict get $master_pl $mname]
            set pin_name [format "S%02d_AXIS" $i]
            set pin [get_bd_intf_pins -quiet axis_noc_0/$pin_name]
            
            if {$pin eq ""} {
                puts "WARN: AXIS pin '$pin_name' not found on axis_noc_0, skipping"
                continue
            }

            puts "INFO: Placing AXIS master $mname ($pin_name) at $loc"
            set_property -dict [list CONFIG.PHYSICAL_LOC $loc] $pin
            incr applied_count
        }
    }

    # Apply slave placements (slaves connect to M-ports on axis_noc_0)
    if {[dict exists $placement_dict slave_placement]} {
        set slave_pl [dict get $placement_dict slave_placement]
        foreach sname [dict keys $slave_pl] {
            if {![info exists s_index($sname)]} {
                puts "WARN: AXIS placement for unknown slave '$sname', skipping"
                continue
            }
            set j $s_index($sname)
            set loc [dict get $slave_pl $sname]
            set pin_name [format "M%02d_AXIS" $j]
            set pin [get_bd_intf_pins -quiet axis_noc_0/$pin_name]
            
            if {$pin eq ""} {
                puts "WARN: AXIS pin '$pin_name' not found on axis_noc_0, skipping"
                continue
            }

            puts "INFO: Placing AXIS slave $sname ($pin_name) at $loc"
            set_property -dict [list CONFIG.PHYSICAL_LOC $loc] $pin
            incr applied_count
        }
    }

    puts "INFO: Applied $applied_count AXIS physical placements"
    return $applied_count
}

# === Per-edge QoS on each SI (CONFIG.CONNECTIONS) ===
proc _configure_aximm_noc_qos {P conns m_index_aximm s_index_aximm num_aximm_tg} {
    upvar 1 $m_index_aximm m_index
    upvar 1 $s_index_aximm s_index
    foreach mname [dict keys $conns] {
        puts "Mname: $mname"
        if {![info exists m_index($mname)]} {
            continue
        }
        set i $m_index($mname)
        puts "i: $i"

        # Determine SI pin name based on whether this is an HBM master or regular master
        if {$i >= $num_aximm_tg} {
            # HBM master: use HBMxx_AXI naming (index relative to HBM masters)
            set hbm_idx [expr {$i - $num_aximm_tg}]
            set si_pin [get_bd_intf_pins axi_noc_0/[format "HBM%02d_AXI" $hbm_idx]]
        } else {
            # Regular AXIMM master: use Sxx_AXI naming
            set si_pin [get_bd_intf_pins axi_noc_0/[format "S%02d_AXI" $i]]
        }
        set entries ""
        foreach ent [dict get $conns $mname] {
            set to [dict get $ent to]

            # Check if destination is an HBM port (format: hbmX_portY)
            if {[regexp {^hbm(\d+)_port(\d+)$} $to -> ctrl_num port_num]} {
                # HBM slave: use HBMx_PORTy naming (uppercase)
                set mi [format "HBM%d_PORT%d" $ctrl_num $port_num]
                puts "HBM mi: $mi"
            } elseif {[regexp {^MC_(\d+)$} $to -> port_num]} {
                # DDR slave: use MC_X naming (maps to MC_PORT)
                set mi [format "MC_%d" $port_num]
                puts "DDR mi: $mi"
            } elseif {[info exists s_index($to)]} {
                # Regular AXIMM slave
                set j $s_index($to)
                set mi [format "M%02d_AXI" $j]
                puts "mi: $mi"
            } else {
                continue
            }
            set seg "$mi {"

            # --- QoS settings (same as before) ---
            if {[dict exists $ent qos read_bw]} {
                append seg " read_bw {[dict get $ent qos read_bw]}"
            } elseif {[dict exists $P qos_read_bw]} {
                append seg " read_bw {[dict get $P qos_read_bw]}"
            }
            if {[dict exists $ent qos write_bw]} {
                append seg " write_bw {[dict get $ent qos write_bw]}"
            } elseif {[dict exists $P qos_write_bw]} {
                append seg " write_bw {[dict get $P qos_write_bw]}"
            }
            if {[dict exists $ent qos read_avg_burst]} {
                append seg " read_avg_burst {[dict get $ent qos read_avg_burst]}"
            } elseif {[dict exists $P qos_avg_burst]} {
                append seg " read_avg_burst {[dict get $P qos_avg_burst]}"
            }

            if {[dict exists $ent qos write_avg_burst]} {
                append seg " write_avg_burst {[dict get $ent qos write_avg_burst]}"
            } elseif {[dict exists $P qos_avg_burst]} {
                append seg " write_avg_burst {[dict get $P qos_avg_burst]}"
            }

            append seg " }"
            append entries " $seg"
        }
        if {$entries ne ""} {
            puts "set_property -dict [list CONFIG.CONNECTIONS $entries] $si_pin"
            set_property -dict [list CONFIG.CONNECTIONS $entries] $si_pin
        }
    }
}



proc _configure_axis_noc_qos {P conns m_index_axis s_index_axis data_width_bits} {
    upvar 1 $m_index_axis m_index
    upvar 1 $s_index_axis s_index

    foreach mname [dict keys $conns] {
        set i ""
        if {[info exists m_index($mname)]} {
            set i $m_index($mname)
        } elseif {[info exists m_index(axis_${mname})]} {
             set i $m_index(axis_${mname})
        } elseif {[regsub {^axis_} $mname "" short_name] && [info exists m_index($short_name)]} {
             set i $m_index($short_name)
        }

        if {$i eq ""} {
            # _warn {AXISNOC-0002} "Could not find AXIS master '$mname' (or 'axis_$mname' / without prefix) in m_index. Skipping QoS/Monitor."
            continue
        }
        
        set si_pin [get_bd_intf_pins axis_noc_0/[format "S%02d_AXIS" $i]]

        set ent_list [dict get $conns $mname]

        if {[llength $ent_list] > 1} {
            set extras {}
            for {set k 1} {$k < [llength $ent_list]} {incr k} {
                set e [lindex $ent_list $k]
                if {[dict exists $e to]} { lappend extras [dict get $e to] }
            }
            _warn {AXISNOC-0001} "Master '$mname' has multiple destinations {[join $extras , ]}; multi-dest not supported yet. Using only the first."
            set ent_list [lrange $ent_list 0 0]
        }

        set entries ""
        set mi_pin ""
        foreach ent $ent_list {
            set to [dict get $ent to]
            if {![info exists s_index($to)]} {
                continue
            }
            set j  $s_index($to)
            set mi [format "M%02d_AXIS" $j]
            set mi_pin [get_bd_intf_pins -quiet axis_noc_0/$mi]

            set seg "$mi {"
            # --- Write BW (AXIS only has write) ---
            if {[dict exists $ent qos write_bw]} {
                append seg " write_bw {[dict get $ent qos write_bw]}"
            } elseif {[dict exists $P qos_write_bw]} {
                append seg " write_bw {[dict get $P qos_write_bw]}"
            }

            # --- Write Avg Burst (AXIS only has write) ---
            if {[dict exists $ent qos write_avg_burst]} {
                append seg " write_avg_burst {[dict get $ent qos write_avg_burst]}"
            } elseif {[dict exists $P qos_avg_burst]} {
                append seg " write_avg_burst {[dict get $P qos_avg_burst]}"
            }
            append seg " }"
            append entries " $seg"
        }

        if {$entries ne ""} {
            set_property -dict [list CONFIG.CONNECTIONS $entries] $si_pin

            set monitor_name  "axis_monitor_wrapper_$i"
            create_bd_cell -type module -reference axis_monitor_wrapper $monitor_name
            set_property CONFIG.SRC_ID $i [get_bd_cells $monitor_name]
            set_property CONFIG.TDATA_WIDTH $data_width_bits [get_bd_cells $monitor_name]
            connect_bd_net [get_bd_pins noc_clk_gen/axi_clk_0]   [get_bd_pins $monitor_name/aclk]
            connect_bd_net [get_bd_pins noc_clk_gen/axi_rst_0_n] [get_bd_pins $monitor_name/aresetn]
            connect_bd_intf_net $si_pin [get_bd_intf_pins $monitor_name/MON_AXIS_IN]
            connect_bd_intf_net $mi_pin [get_bd_intf_pins $monitor_name/MON_AXIS_OUT]
        }
    }
}

proc _create_aximm_noc_from_topology {P topo master_list slave_list hbm_master_list hbm_slave_list num_aximm_tg num_aximm_end num_hbm_tg num_hbm_end ddr_config m_index_out s_index_out} {
    # Return m_index and s_index arrays via upvar for use by placement
    upvar 1 $m_index_out m_index
    upvar 1 $s_index_out s_index

    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_noc:1.1 axi_noc_0
    set_property -dict [list CONFIG.NUM_SI $num_aximm_tg CONFIG.NUM_MI $num_aximm_end] [get_bd_cells axi_noc_0]
    set_property CONFIG.NUM_HBM_BLI $num_hbm_tg [get_bd_cells axi_noc_0]
    connect_bd_net [get_bd_pins axi_noc_0/aclk0]   [get_bd_pins noc_clk_gen/axi_clk_0]

     # === Masters: perf_axi_tg ===
    array set m_index {}
    for {set i 0} {$i < $num_aximm_tg} {incr i} {
        set md    [lindex $master_list $i]
        set mname [dict get $md name]
        set monitor_name  "axi_pmon_$i"

        _create_aximm_tg $mname $monitor_name $i [dict get $P tg_axi_data_width_bits]
        _apply_aximm_tg_address_config $mname $md
        set m_index($mname) $i
    }

    for {set i 0} {$i < $num_hbm_tg} {incr i} {
        set list_idx [expr {$i + $num_aximm_tg}]
        set md    [lindex $hbm_master_list $i]
        set mname [dict get $md name]
        set monitor_name  "axi_pmon_$list_idx"
        _create_hbm_tg $mname $monitor_name $i [dict get $P tg_axi_data_width_bits] $list_idx
        _apply_aximm_tg_address_config $mname $md
        set m_index($mname) $list_idx
    }

    # === Slaves: axi_bram_ctrl + blk_mem_gen ===
    array set s_index {}
    set bram_width_bits [expr {[dict exists $P bram_data_width] ? [dict get $P bram_data_width] : 512}]

    for {set j 0} {$j < $num_aximm_end} {incr j} {
        set sd    [lindex $slave_list $j]
        set sname [dict get $sd name]
        set bc  "bc_$sname"
        set mem "mem_$sname"

       _create_bram_endpoint $bc $mem $j $bram_width_bits
        set s_index($sname) $j
    }

    set num_hbm_chnl [expr {($num_hbm_end + 1) / 2}]
    set_property CONFIG.HBM_NUM_CHNL $num_hbm_chnl [get_bd_cells axi_noc_0]


    set num_mc              [dict get $ddr_config num_mc]
    set num_ports_per_mc    [dict get $ddr_config num_ports_per_mc]
    set interleave_size     [dict get $ddr_config interleave_size_bytes]
    set_property CONFIG.NUM_MC $num_mc [get_bd_cells axi_noc_0]
    set_property CONFIG.NUM_MCP $num_ports_per_mc [get_bd_cells axi_noc_0]
    set_property CONFIG.MC_INTERLEAVE_SIZE $interleave_size [get_bd_cells axi_noc_0]

    # Create external pins for each DDR memory controller
    set_property CONFIG.USER_NUM_OF_SYS_CLK $num_mc [get_bd_cells noc_clk_gen]
    for {set mc 0} {$mc < $num_mc} {incr mc} {
        connect_bd_intf_net [get_bd_intf_pins noc_clk_gen/SYS_CLK${mc}] [get_bd_intf_pins axi_noc_0/sys_clk${mc}]
        make_bd_intf_pins_external  [get_bd_intf_pins noc_clk_gen/SYS_CLK${mc}_IN]
        # make_bd_intf_pins_external [get_bd_intf_pins axi_noc_0/sys_clk${mc}]
        make_bd_intf_pins_external [get_bd_intf_pins axi_noc_0/CH0_DDR4_${mc}]
    }

    set conns [dict get $topo connections]
    _configure_aximm_noc_qos $P $conns m_index s_index $num_aximm_tg

    assign_bd_address

    # assign_bd_address can refresh perf_axi_tg address properties back to the
    # slave segment base. Reapply conn-json address overrides after Vivado's
    # address map is established so generated IP and simulation metadata agree.
    for {set i 0} {$i < $num_aximm_tg} {incr i} {
        set md    [lindex $master_list $i]
        set mname [dict get $md name]
        _apply_aximm_tg_address_config $mname $md
    }
    for {set i 0} {$i < $num_hbm_tg} {incr i} {
        set md    [lindex $hbm_master_list $i]
        set mname [dict get $md name]
        _apply_aximm_tg_address_config $mname $md
    }
}

proc _create_axis_noc_from_topology {P topo master_list slave_list num_aximm_tg num_end tg_offset axis_m_index_var axis_s_index_var} {
    upvar 1 $axis_m_index_var axis_m_idx_out
    upvar 1 $axis_s_index_var axis_s_idx_out
    
    # puts "--------------!!! tg_offset: $tg_offset !!!"
    add_files -norecurse [list \
        [file join $::SWEEP_ROOT lib axis_monitor_wrapper.v] \
        [file join $::SWEEP_ROOT lib axis_endpoint.v] \
        [file join $::SWEEP_ROOT lib axis_monitor.sv] \
    ]
    update_compile_order -fileset sources_1
    update_compile_order -fileset sim_1

    create_bd_cell -type ip -vlnv xilinx.com:ip:axis_noc:1.0 axis_noc_0
    connect_bd_net [get_bd_pins axis_noc_0/aclk0]   [get_bd_pins noc_clk_gen/axi_clk_0]
    set_property -dict [list \
        CONFIG.NUM_MI $num_end \
        CONFIG.NUM_SI $num_aximm_tg \
    ] [get_bd_cells axis_noc_0]

     # === Masters: perf_axi_tg or axis_fifo (M_AXIS side) ===
    array set m_index {}
    array set created_fifos {}  ;# Track FIFOs we've created
    for {set i 0} {$i < $num_aximm_tg} {incr i} {
        set md    [lindex $master_list $i]
        set mname [dict get $md name]
        set mtype [expr {[dict exists $md type] ? [dict get $md type] : "axis_tg"}]
        
        if {$mtype eq "axis_fifo"} {
            # FIFO master side - remember index, create FIFO later when we see slave side
            set m_index($mname) $i
            # Extract base FIFO name (strip _M_AXIS suffix if present)
            set fifo_base [regsub {_M_AXIS$} $mname ""]
            set created_fifos($fifo_base,m_idx) $i
        } else {
            set num_pkt [expr {[dict exists $P num_write_transactions_cfg] ? [dict get $P num_write_transactions_cfg] : 50}]
            _create_axis_tg $P $mname $i [dict get $P tg_axi_data_width_bits] $tg_offset $num_pkt
            set m_index($mname) $i
        }
    }

    # === Slaves: axis_endpoint or axis_fifo (S_AXIS side) ===
    array set s_index {}
    set bram_width_bits [expr {[dict exists $P bram_data_width] ? [dict get $P bram_data_width] : 512}]

    for {set j 0} {$j < $num_end} {incr j} {
        set sd    [lindex $slave_list $j]
        set sname [dict get $sd name]
        set stype [expr {[dict exists $sd type] ? [dict get $sd type] : "axis_end"}]
        
        if {$stype eq "axis_fifo"} {
            # FIFO slave side
            set s_index($sname) $j
            # Extract base FIFO name (strip _S_AXIS suffix if present)
            set fifo_base [regsub {_S_AXIS$} $sname ""]
            set created_fifos($fifo_base,s_idx) $j
            
            # If we have both indices, create the FIFO now
            if {[info exists created_fifos($fifo_base,m_idx)]} {
                set m_idx $created_fifos($fifo_base,m_idx)
                set s_idx $j
                _create_axis_fifo $fifo_base $m_idx $s_idx
            }
        } else {
            _create_axis_endpoint $sname $j $bram_width_bits
            set s_index($sname) $j
        }
    }

    set conns [dict get $topo connections]
    # _configure_axis_noc_qos $conns m_index s_index $bram_width_bits
    _configure_axis_noc_qos $P $conns m_index s_index $bram_width_bits

    # Copy index arrays to output variables for placement
    array set axis_m_idx_out [array get m_index]
    array set axis_s_idx_out [array get s_index]
}

# Build a block design from a topology dict:
# topo schema:
# {
#   masters:     list of {name type}          ;# e.g. { {name tg_0 type perf_axi_tg} ... }
#   slaves:      list of {name type}          ;# e.g. { {name bram_0 type axi_bram} ... }
#   connections: dict masterName -> list of {to slaveName  qos {read_bw 1000 write_bw 1000 ...}}
# }
# Optional: placement_dict for physical NOC endpoint locations
# Optional: sim_mode for SystemC TLM simulation ("tlm" or "" for RTL)
proc _build_bd_from_topology {P topo {placement_dict {}} {sim_mode {}}} {
    # Extract lists
    set aximm_masters [_dict_get_list_or_empty $topo aximm_masters]
    set aximm_slaves  [_dict_get_list_or_empty $topo aximm_slaves]
    set hbm_masters [_dict_get_list_or_empty $topo hbm_masters]
    set hbm_slaves  [_parse_hbm_settings $topo hbm_settings]
    set axis_masters  [_dict_get_list_or_empty $topo axis_masters]
    set axis_slaves   [_dict_get_list_or_empty $topo axis_slaves]
    set ddr_config [_parse_ddr_settings $topo ddr_settings]


    set num_aximm_tg [llength $aximm_masters]
    set num_aximm_end [llength $aximm_slaves]
    set num_hbm_tg [llength $hbm_masters]
    set num_hbm_end [llength $hbm_slaves]
    set num_axis_tg  [llength $axis_masters]
    set num_axis_end [llength $axis_slaves]
    
    # Count only actual TGs (not FIFOs) for sim_trig
    set num_axis_tg_only 0
    foreach m $axis_masters {
        set mtype [expr {[dict exists $m type] ? [dict get $m type] : "axis_tg"}]
        if {$mtype eq "axis_tg" || $mtype eq "perf_axi_tg"} {
            incr num_axis_tg_only
        }
    }

    # (Re)create BD
    _recreate_bd [dict get $P bd_name]

    # Use num_axis_tg_only to exclude FIFOs from sim_trig count
    set num_tg   [expr {$num_aximm_tg + $num_axis_tg_only + $num_hbm_tg}]
    _create_common_components [dict get $P noc_axi_clk_mhz] $num_tg

    set_property -name {xsim.simulate.log_all_signals} -value {true} -objects [get_filesets sim_1]

    # Arrays to track name->index mappings for placements
    array set mm_m_index {}
    array set mm_s_index {}
    array set axis_m_index {}
    array set axis_s_index {}

    # === AXI NoC ===
    if {$num_aximm_tg > 0 || $num_aximm_end > 0 || $num_hbm_tg > 0 || $num_hbm_end > 0} {
        _create_aximm_noc_from_topology $P $topo $aximm_masters $aximm_slaves $hbm_masters $hbm_slaves $num_aximm_tg $num_aximm_end $num_hbm_tg $num_hbm_end $ddr_config mm_m_index mm_s_index
    }
    # === AXIS NoC ===
    if {$num_axis_tg > 0 || $num_axis_end > 0} {
        _create_axis_noc_from_topology $P $topo $axis_masters $axis_slaves $num_axis_tg $num_axis_end $num_aximm_tg axis_m_index axis_s_index
    }

    # Save before validate so you can debug in GUI if validate fails
    save_bd_design
    validate_bd_design

    # Apply physical placements after initial validation
    if {$placement_dict ne {} && [dict size $placement_dict] > 0} {
        puts "INFO: Applying physical NOC placements..."
        
        # Apply AXIMM placements
        if {$num_aximm_tg > 0 || $num_aximm_end > 0 || $num_hbm_tg > 0 || $num_hbm_end > 0} {
            _apply_noc_placements $placement_dict mm_m_index mm_s_index $num_aximm_tg
        }
        
        # Apply AXIS placements
        if {$num_axis_tg > 0 || $num_axis_end > 0} {
            _apply_axis_noc_placements $placement_dict axis_m_index axis_s_index
        }

        # Re-validate after applying placements
        puts "INFO: Re-validating design with placements..."
        validate_bd_design
    }

    save_bd_design

    if {[dict exists $P custom_ncr] && [dict get $P custom_ncr] ne ""} {
        set custom_ncr [dict get $P custom_ncr]
        if {[dict exists $P custom_nts] && [dict get $P custom_nts] ne ""} {
            set custom_nts [dict get $P custom_nts]
            if {[file rootname $custom_ncr] ne [file rootname $custom_nts]} {
                error "ERROR: custom_ncr and custom_nts must share the same base path: $custom_ncr vs $custom_nts"
            }
            puts "INFO: Custom NoC traffic sidecar is $custom_nts"
        }
        puts "INFO: Reading custom NoC solution from $custom_ncr"
        # The BD must be open. Usually validation opens it, but we can just call it here:
        read_noc_solution -file $custom_ncr
    }

    puts "INFO: Locking all NoC routes..."
    set noc_routes [get_noc_net_routes -of [get_noc_logical_paths]] 
    foreach noc_route $noc_routes {
        set_property LOCK true $noc_route  
    }

    # Apply SystemC TLM simulation mode if specified
    if {$sim_mode eq "tlm"} {
        puts "INFO: Setting simulation mode to SystemC TLM..."
        foreach noc_inst {axi_noc_0 axis_noc_0} {
            set cell [get_bd_cells -quiet /$noc_inst]
            if {$cell ne ""} {
                puts "INFO: localized $cell for TLM simulation model"
                set_property SELECTED_SIM_MODEL tlm $cell
            }
        }
    }

    _wrap_and_set_top [dict get $P bd_name]
    set_property sim.use_ip_compiled_libs 0 [current_project]
    if {$num_axis_tg > 0 || $num_axis_end > 0} {

        generate_target simulation [get_files [dict get $P bd_name].bd]
    }
}
