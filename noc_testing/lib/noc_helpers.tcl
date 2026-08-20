# ============================ Helpers ========================================

proc _sxx_name {i} { return [format "S%02d_AXI" $i] }
proc _mxx_name {i} { return [format "M%02d_AXI" $i] }

proc _wrap_and_set_top {bd_name} {
  set bd_obj [get_files -quiet */bd/$bd_name/${bd_name}.bd]
  if {[llength $bd_obj] == 0} { set bd_obj [get_files -quiet *${bd_name}.bd] }
  if {[llength $bd_obj] == 0} { puts "ERROR: Could not find ${bd_name}.bd"; exit 1 }
  make_wrapper -files $bd_obj -top -import
  set wrapper_v [lindex [get_files -quiet */bd/$bd_name/hdl/${bd_name}_wrapper.v] 0]
  puts "INFO: Wrapper: $wrapper_v"
  update_compile_order -fileset sources_1
  set_property top ${bd_name}_wrapper [current_fileset]
  set_property top ${bd_name}_wrapper [get_filesets sim_1]
  update_compile_order -fileset sim_1
}

# ==== Write NoC descriptor files (.ncr/.nts) for the current topology ====
proc collect_noc_descriptors {P out_dir key} {
  set pn [dict get $P project_name]
  set pd [file normalize [dict get $P project_dir]]
  set bd [dict get $P bd_name]

  # Source paths from standard Vivado layout
  set nsln_dir [file normalize [file join $pd "${pn}.gen" "sources_1" "bd" $bd "nsln"]]
  set ncr_src  [file join $nsln_dir "${bd}.ncr"]
  set nts_src  [file join $nsln_dir "${bd}.nts"]
  if {![file exists $ncr_src] || ![file exists $nts_src]} {
    puts "WARN: NoC descriptor not found in $nsln_dir"
    return
  }

  # Destination under out_root
  file mkdir $out_dir
  set ncr_dst [file join $out_dir "${bd}.ncr"]
  set nts_dst [file join $out_dir "${bd}.nts"]
  file copy -force $ncr_src $ncr_dst
  file copy -force $nts_src $nts_dst

  # Base path for gem5
  set base [file rootname [file join $out_dir $bd]]

  puts [format "ARTIFACT:TOPO=%s BASE=%s NCR=%s NTS=%s" $key $base $ncr_dst $nts_dst]
}

# ============================ TG props =======================================
proc _cells_with_user_tg_props {} {
  # Find all Traffic Generator instances directly by their IP type.
  set tg_cells [get_bd_cells -hier -quiet -filter {VLNV =~ "*:perf_axi_tg:*"}]
  return [lsort -dictionary $tg_cells]
}

# Like your delta setter, but accepts per-cell overrides: {cellName {K1 V1 K2 V2 ...} ...}
proc _set_user_tg_props_delta {defaults {per_cell {}}} {
  set cells [_cells_with_user_tg_props]
  set changed {}
  foreach c $cells {
    set cell_cfg $defaults
    set short_name [file tail $c]
    if {[dict exists $per_cell $c]} {
      set cell_cfg [dict merge $cell_cfg [dict get $per_cell $c]]
    } elseif {[dict exists $per_cell $short_name]} {
      set cell_cfg [dict merge $cell_cfg [dict get $per_cell $short_name]]
    }

    set changed_here 0
    foreach {k v} $cell_cfg {
      if {![string match "USER_C_AXI_*" $k]} { continue }
      set prop "CONFIG.$k"
      if {![catch {get_property $prop $c} cur]} {
        if {$cur ne $v} {
          catch {set_property $prop $v $c}
          set changed_here 1
        }
      }
    }
    if {$changed_here} { lappend changed $c }
  }
  return $changed
}

proc _vivado_tg_clock_mhz {P} {
  if {$P ne "" && [dict exists $P noc_axi_clk_mhz]} {
    set clk [_to_int [dict get $P noc_axi_clk_mhz]]
    if {$clk ne "" && $clk > 0} { return $clk }
  }
  return 1000
}

proc _vivado_tg_max_bandwidth_mbps {size_bytes clock_mhz} {
  if {$size_bytes eq "" || $size_bytes <= 0} { set size_bytes 16 }
  if {$clock_mhz eq "" || $clock_mhz <= 0} { set clock_mhz 1000 }
  set max_bw [expr {$size_bytes * $clock_mhz}]
  if {$max_bw > 19200} { set max_bw 19200 }
  return $max_bw
}

proc _validate_vivado_tg_burst {combo label size_key len_key} {
  if {![dict exists $combo $size_key] || ![dict exists $combo $len_key]} {
    return
  }
  set size [_to_int [dict get $combo $size_key]]
  set len [_to_int [dict get $combo $len_key]]
  if {$size eq "" || $size <= 0} {
    error "Vivado AXI-MM TG $label size must be a positive integer."
  }
  if {$len eq "" || $len < 0} {
    error "Vivado AXI-MM TG $label length is AWLEN-style and must be >= 0."
  }
  set bytes [expr {$size * ($len + 1)}]
  if {$bytes > 4096} {
    error "Vivado AXI-MM TG $label transaction must be <= 4096 bytes; size=$size and len=$len imply $bytes."
  }
}

proc _normalize_vivado_tg_bandwidth {combo bw_key size_key clock_mhz} {
  if {![dict exists $combo $bw_key]} {
    return $combo
  }
  set bw [_to_int [dict get $combo $bw_key]]
  if {$bw eq ""} {
    error "Vivado AXI-MM TG bandwidth '$bw_key' must be an integer MBps value."
  }
  set size ""
  if {[dict exists $combo $size_key]} {
    set size [_to_int [dict get $combo $size_key]]
  }
  set max_bw [_vivado_tg_max_bandwidth_mbps $size $clock_mhz]
  if {$bw <= 0 || $bw > $max_bw} {
    dict set combo $bw_key $max_bw
  }
  return $combo
}

proc _finalize_vivado_tg_config {combo P} {
  set clock_mhz [_vivado_tg_clock_mhz $P]

  if {![dict exists $combo USER_C_AXI_READ_SIZE] && [dict exists $combo USER_C_AXI_WRITE_SIZE]} {
    dict set combo USER_C_AXI_READ_SIZE [dict get $combo USER_C_AXI_WRITE_SIZE]
  }
  if {![dict exists $combo USER_C_AXI_READ_LEN] && [dict exists $combo USER_C_AXI_WRITE_LEN]} {
    dict set combo USER_C_AXI_READ_LEN [dict get $combo USER_C_AXI_WRITE_LEN]
  }

  _validate_vivado_tg_burst $combo write USER_C_AXI_WRITE_SIZE USER_C_AXI_WRITE_LEN
  _validate_vivado_tg_burst $combo read USER_C_AXI_READ_SIZE USER_C_AXI_READ_LEN

  set combo [_normalize_vivado_tg_bandwidth $combo USER_C_AXI_WRITE_BANDWIDTH USER_C_AXI_WRITE_SIZE $clock_mhz]
  if {![dict exists $combo USER_C_AXI_READ_BANDWIDTH] && [dict exists $combo USER_C_AXI_WRITE_BANDWIDTH]} {
    dict set combo USER_C_AXI_READ_BANDWIDTH [dict get $combo USER_C_AXI_WRITE_BANDWIDTH]
  }
  set combo [_normalize_vivado_tg_bandwidth $combo USER_C_AXI_READ_BANDWIDTH USER_C_AXI_READ_SIZE $clock_mhz]

  return $combo
}

proc _parse_topology_from_json {path} {
    package require json
    set p $path
    if {![file exists $p] && [info exists ::SWEEP_ROOT]} {
        set maybe [file join $::SWEEP_ROOT $path]
        if {[file exists $maybe]} { set p $maybe }
    }
    if {![file exists $p]} {
        error "Topology JSON file not found: $path"
    }
    set f [open $p r]
    set txt [read $f]
    close $f
    set topo [json::json2dict $txt]
    if {[dict exists $topo kind] && [dict get $topo kind] eq "naviq.connections"} {
        return [_v2_connections_to_legacy_topology $topo]
    }
    return $topo
}

proc _v2_port_endpoint {component_id port_name} {
    return "${component_id}.${port_name}"
}

proc _v2_component_supported_for_vivado {component_id node_type} {
    switch -- $node_type {
        "AxiRandomTrafficGenerator" -
        "AxisRandomTrafficGenerator" -
        "AxisPacketTrafficGenerator" -
        "AxisSinkNode" -
        "AxisPacketCheckerSink" -
        "AxisFifoNode" -
        "BramEndpoint" -
        "tileNSU_HBM" {
            return 1
        }
        default {
            error "V2 topology component '$component_id' uses node_type '$node_type', which is not supported by the current Vivado/Tcl generator."
        }
    }
}

proc _v2_is_hbm_port {node_type port_dict component_id} {
    set hint [string tolower "$node_type $component_id"]
    if {[dict exists $port_dict type]} { append hint " [dict get $port_dict type]" }
    return [expr {[string first "hbm" $hint] >= 0}]
}

proc _v2_is_ddr_port {node_type port_dict component_id} {
    set hint [string tolower "$node_type $component_id"]
    if {[dict exists $port_dict type]} { append hint " [dict get $port_dict type]" }
    return [expr {[string first "ddr" $hint] >= 0}]
}

proc _v2_connections_to_legacy_topology {topo} {
    set legacy [dict create]
    set aximm_masters {}
    set aximm_slaves {}
    set axis_masters {}
    set axis_slaves {}
    set hbm_masters {}
    set hbm_endpoints {}
    set endpoint_component [dict create]

    set components [dict get $topo components]
    foreach component_id [dict keys $components] {
        set component [dict get $components $component_id]
        set node_type [_dget $component node_type ""]
        _v2_component_supported_for_vivado $component_id $node_type

        set ports [_dget $component ports {}]
        foreach port_name [dict keys $ports] {
            set port [dict get $ports $port_name]
            set role [string tolower [_dget $port role ""]]
            set protocol [string tolower [_dget $port protocol ""]]
            set endpoint [_v2_port_endpoint $component_id $port_name]
            dict set endpoint_component $endpoint $component_id

            if {$role eq "master" && $protocol eq "aximm"} {
                set master [dict create name $component_id type "perf_axi_tg"]
                if {[dict exists $component params]} {
                    dict set master params [dict get $component params]
                }
                dict set master port_config $port
                lappend aximm_masters $master
            } elseif {$role eq "slave" && $protocol eq "aximm"} {
                if {[_v2_is_hbm_port $node_type $port $component_id]} {
                    lappend hbm_endpoints [dict create name $component_id]
                } elseif {[_v2_is_ddr_port $node_type $port $component_id]} {
                    # DDR endpoints are derived from ddr_settings by _parse_ddr_settings.
                    # Keep the connection target name as-is.
                } else {
                    lappend aximm_slaves [dict create name $component_id type "axi_bram"]
                }
            } elseif {$role eq "master" && $protocol eq "axis"} {
                set mtype "perf_axi_tg"
                if {$node_type eq "AxisFifoNode"} { set mtype "axis_fifo" }
                lappend axis_masters [dict create name $component_id type $mtype]
            } elseif {$role eq "slave" && $protocol eq "axis"} {
                set stype "axis_endpoint"
                if {$node_type eq "AxisFifoNode"} { set stype "axis_fifo" }
                lappend axis_slaves [dict create name $component_id type $stype]
            } else {
                error "V2 endpoint '$endpoint' must declare role master/slave and protocol aximm/axis."
            }
        }
    }

    if {[llength $aximm_masters] > 0} { dict set legacy aximm_masters $aximm_masters }
    if {[llength $aximm_slaves] > 0} { dict set legacy aximm_slaves $aximm_slaves }
    if {[llength $axis_masters] > 0} { dict set legacy axis_masters $axis_masters }
    if {[llength $axis_slaves] > 0} { dict set legacy axis_slaves $axis_slaves }
    if {[llength $hbm_endpoints] > 0} { dict set legacy hbm_endpoints $hbm_endpoints }
    if {[dict exists $topo hbm_settings]} { dict set legacy hbm_settings [dict get $topo hbm_settings] }
    if {[dict exists $topo ddr_settings]} { dict set legacy ddr_settings [dict get $topo ddr_settings] }

    set connections [dict create]
    foreach edge [_dict_get_list_or_empty $topo connections] {
        set from_ep [dict get $edge from]
        set to_ep [dict get $edge to]
        if {![dict exists $endpoint_component $from_ep] || ![dict exists $endpoint_component $to_ep]} {
            error "V2 connection references unknown endpoint '$from_ep' or '$to_ep'."
        }
        set from_comp [dict get $endpoint_component $from_ep]
        set to_comp [dict get $endpoint_component $to_ep]
        set ent [dict create to $to_comp]
        if {[dict exists $edge qos]} { dict set ent qos [dict get $edge qos] }
        if {[dict exists $connections $from_comp]} {
            set cur [dict get $connections $from_comp]
        } else {
            set cur {}
        }
        lappend cur $ent
        dict set connections $from_comp $cur
    }
    dict set legacy connections $connections

    return $legacy
}

# Parse placement JSON file for physical NOC endpoint locations
# Returns: dict with master_placement and slave_placement mappings
# Example JSON: {"master_placement": {"tg_0": "NOC_NMU512_X0Y18"}, "slave_placement": {"bram_0": "NOC_NSU512_X0Y18"}}
proc _parse_placement_json {path} {
    package require json
    set p $path
    if {![file exists $p] && [info exists ::SWEEP_ROOT]} {
        set maybe [file join $::SWEEP_ROOT $path]
        if {[file exists $maybe]} { set p $maybe }
    }
    if {![file exists $p]} {
        puts "INFO: Placement JSON not found at $path, skipping placements"
        return [dict create master_placement {} slave_placement {}]
    }
    set f [open $p r]
    set txt [read $f]
    close $f
    set placement_dict [json::json2dict $txt]

    if {[dict exists $placement_dict kind] && [dict get $placement_dict kind] eq "naviq.placement"} {
        set converted [dict create master_placement {} slave_placement {} ddr_placement {}]
        set placements [dict get $placement_dict placements]
        foreach endpoint [dict keys $placements] {
            set physical [dict get $placements $endpoint]
            set component [lindex [split $endpoint .] 0]
            if {[string first "NMU" $physical] >= 0} {
                dict set converted master_placement $component $physical
            } elseif {[string first "DDRMC" $physical] >= 0 && [regexp {^MC_(\d+)$} $component -> mc_idx]} {
                dict set converted ddr_placement "CH0_DDR4_${mc_idx}" $physical
            } elseif {[string first "NSU" $physical] >= 0 || [string first "HBM_MC" $physical] >= 0 || [string first "DDRMC" $physical] >= 0} {
                dict set converted slave_placement $component $physical
            } else {
                puts "WARN: Could not classify v2 placement '$endpoint' -> '$physical'; skipping."
            }
        }
        set placement_dict $converted
    }

    # Ensure all keys exist with defaults
    if {![dict exists $placement_dict master_placement]} {
        dict set placement_dict master_placement {}
    }
    if {![dict exists $placement_dict slave_placement]} {
        dict set placement_dict slave_placement {}
    }
    if {![dict exists $placement_dict ddr_placement]} {
        dict set placement_dict ddr_placement {}
    }

    puts "INFO: Loaded placement JSON from $p"
    return $placement_dict
}

# --- Default topology dict (all-to-all), derived from counts in P ---
proc _default_topology_dict_from_P {P} {
    set topo_dict [dict create]
    set connections [dict create]

    set qos_dict [dict create]
    if {[dict exists $P qos_read_bw]}   { dict set qos_dict read_bw [dict get $P qos_read_bw] }
    if {[dict exists $P qos_write_bw]}  { dict set qos_dict write_bw [dict get $P qos_write_bw] }
    if {[dict exists $P qos_avg_burst]} {
        dict set qos_dict read_avg_burst  [dict get $P qos_avg_burst]
        dict set qos_dict write_avg_burst [dict get $P qos_avg_burst]
    }

    # --- 1. Build AXI-MM components (if configured) ---
    set m_aximm [_dget $P num_aximm_tg 0]
    set s_aximm [_dget $P num_aximm_bram 0]

    if {$m_aximm > 0} {
        set masters {}
        for {set i 0} {$i < $m_aximm} {incr i} {
            lappend masters [dict create name "tg_aximm_$i" type "perf_axi_tg"]
        }
        dict set topo_dict aximm_masters $masters
    }
    if {$s_aximm > 0} {
        set slaves {}
        for {set j 0} {$j < $s_aximm} {incr j} {
            lappend slaves [dict create name "bram_aximm_$j" type "axi_bram"]
        }
        dict set topo_dict aximm_slaves $slaves
    }
    # Build default AXI-MM (all-to-all) connections
    for {set i 0} {$i < $m_aximm} {incr i} {
        set mname "tg_aximm_$i"
        set edges {}
        for {set j 0} {$j < $s_aximm} {incr j} {
            set ent [dict create to "bram_aximm_$j"]
            if {$qos_dict ne {}} { dict set ent qos $qos_dict }
            lappend edges $ent
        }
        dict set connections $mname $edges
    }

    set m_axis [_dget $P num_axis_tg 0]
    set s_axis [_dget $P num_axis_end 0] ;# Uses the parsed value

    if {$m_axis > 0} {
        set masters {}
        for {set i 0} {$i < $m_axis} {incr i} {
            lappend masters [dict create name "tg_axis_$i" type "perf_axi_tg"]
        }
        dict set topo_dict axis_masters $masters
    }
    if {$s_axis > 0} {
        set slaves {}
        for {set j 0} {$j < $s_axis} {incr j} {
            lappend slaves [dict create name "ep_axis_$j" type "axis_endpoint"]
        }
        dict set topo_dict axis_slaves $slaves
    }

    # Build default AXI-S (1-to-1) connections
    set n_axis_conn [expr {min($m_axis, $s_axis)}]
    for {set i 0} {$i < $n_axis_conn} {incr i} {
        set mname "tg_axis_$i"
        set sname "ep_axis_$i"
        set ent [dict create to $sname]
        # AXI-S only has write qos
        set axis_qos {}
        if {[dict exists $qos_dict write_bw]} { dict set axis_qos write_bw [dict get $qos_dict write_bw] }
        if {[dict exists $qos_dict write_avg_burst]} { dict set axis_qos write_avg_burst [dict get $qos_dict write_avg_burst] }
        if {$axis_qos ne {}} { dict set ent qos $axis_qos }

        dict set connections $mname [list $ent]
    }

    # --- 3. Finalize ---
    dict set topo_dict connections $connections
    return $topo_dict
}

proc _prepare_tg_cell_overrides_from_row {row} {
  set per_cell [dict create]
  foreach k [dict keys $row] {
    if {![string match "vivado.*" $k]} { continue }
    set raw [dict get $row $k]
    if {[string trim $raw] eq ""} { continue }

    set parts [split $k .]
    if {[llength $parts] != 3} {
      error "Invalid Vivado TG override column $k. Expected vivado.<cell>.USER_C_AXI_*."
    }
    set cell [lindex $parts 1]
    set prop [lindex $parts 2]

    if {[string match "USER_C_AXI_*" $prop]} {
      dict set per_cell $cell $prop $raw
    } else {
      error "Invalid Vivado TG override property $prop in column $k."
    }
  }
  return $per_cell
}

proc _prepare_tg_config_from_row {row} {
  set u {}
  set transaction_bytes ""
  set beat_bytes ""
  set beat_count ""

  foreach k {transaction_bytes transaction_size_bytes axi_transaction_size_bytes packet_bytes} {
    if {[dict exists $row $k]} {
      set v [_to_int [dict get $row $k]]
      if {$v ne ""} { set transaction_bytes $v; break }
    }
  }
  foreach k {beat_bytes axi_write_size_bytes write_size_bytes axi_beat_bytes} {
    if {[dict exists $row $k]} {
      set v [_to_int [dict get $row $k]]
      if {$v ne ""} { set beat_bytes $v; break }
    }
  }
  foreach k {beat_count axi_write_len_beats write_len_beats num_beats USER_C_AXIS_PKT_LEN} {
    if {[dict exists $row $k]} {
      set v [_to_int [dict get $row $k]]
      if {$v ne ""} { set beat_count $v; break }
    }
  }

  if {$beat_bytes ne "" && $beat_count ne ""} {
    set derived_bytes [expr {$beat_bytes * ($beat_count + 1)}]
    if {$transaction_bytes ne "" && $transaction_bytes != $derived_bytes} {
      error "Conflicting transaction size settings: transaction_bytes=$transaction_bytes, but beat_bytes=$beat_bytes and beat_count=$beat_count imply $derived_bytes."
    }
    set transaction_bytes $derived_bytes
  } elseif {$transaction_bytes ne "" && ($beat_bytes eq "" || $beat_count eq "")} {
    if {$transaction_bytes <= 0 || ($transaction_bytes % 64) != 0} {
      error "transaction_bytes must be a positive multiple of 64 when Vivado/Tcl beat fields need to be synthesized."
    }
    if {$beat_bytes eq ""} { set beat_bytes 64 }
    if {$beat_count eq ""} { set beat_count [expr {($transaction_bytes / 64) - 1}] }
  }

  # --- Part 1: Translate Aliases and Passthrough ---
  foreach k [dict keys $row] {
    if {[string match "USER_C_AXI_*" $k]} {
      dict set u $k [dict get $row $k]
    }
  }
  if {[dict exists $row axi_write_len_beats]} {
    dict set u USER_C_AXI_WRITE_LEN [_to_int [dict get $row axi_write_len_beats]]
  }
  if {$beat_count ne ""} {
    dict set u USER_C_AXI_WRITE_LEN $beat_count
    dict set u USER_C_AXIS_PKT_LEN $beat_count
  }
  if {[dict exists $row axi_write_bandwidth_cfg_MBps]} {
    dict set u USER_C_AXI_WRITE_BANDWIDTH [_to_int [dict get $row axi_write_bandwidth_cfg_MBps]]
  }
  foreach k {bandwidth_MBps read_write_bandwidth_MBps write_bandwidth_MBps max_write_bandwidth_MBps} {
    if {[dict exists $row $k]} {
      set v [_to_int [dict get $row $k]]
      if {$v ne ""} { dict set u USER_C_AXI_WRITE_BANDWIDTH $v; break }
    }
  }
  foreach k {read_bandwidth_MBps max_read_bandwidth_MBps axi_read_bandwidth_cfg_MBps} {
    if {[dict exists $row $k]} {
      set v [_to_int [dict get $row $k]]
      if {$v ne ""} { dict set u USER_C_AXI_READ_BANDWIDTH $v; break }
    }
  }
  if {[dict exists $row num_write_transactions_cfg]} {
    dict set u USER_C_AXI_NO_OF_WR_TRANS [_to_int [dict get $row num_write_transactions_cfg]]
  }
  foreach k {num_transactions num_packets packet_count transactions} {
    if {[dict exists $row $k]} {
      set v [_to_int [dict get $row $k]]
      if {$v ne ""} { dict set u USER_C_AXI_NO_OF_WR_TRANS $v; break }
    }
  }
  if {[dict exists $row num_read_transactions_cfg]} {
    dict set u USER_C_AXI_NO_OF_RD_TRANS [_to_int [dict get $row num_read_transactions_cfg]]
  }
  foreach k {num_read_transactions read_transactions} {
    if {[dict exists $row $k]} {
      set v [_to_int [dict get $row $k]]
      if {$v ne ""} { dict set u USER_C_AXI_NO_OF_RD_TRANS $v; break }
    }
  }
  if {[dict exists $row axi_write_size_bytes]} {
    set b [_to_int [dict get $row axi_write_size_bytes]]
    if {$b ne ""} { dict set u USER_C_AXI_WRITE_SIZE $b }
  }
  if {$beat_bytes ne ""} {
    dict set u USER_C_AXI_WRITE_SIZE $beat_bytes
  }
  foreach k {axi_read_size_bytes read_size_bytes read_beat_bytes} {
    if {[dict exists $row $k]} {
      set b [_to_int [dict get $row $k]]
      if {$b ne ""} { dict set u USER_C_AXI_READ_SIZE $b; break }
    }
  }
  foreach k {axi_read_len_beats read_len_beats read_beat_count} {
    if {[dict exists $row $k]} {
      set v [_to_int [dict get $row $k]]
      if {$v ne ""} { dict set u USER_C_AXI_READ_LEN $v; break }
    }
  }

  # --- Part 2: Finalize the Configuration Based on tg_mode ---
  set mode ""
  foreach k {tg_mode direction read_write_mode mode} {
    if {[dict exists $row $k]} {
      set v [string tolower [string trim [dict get $row $k]]]
      if {$v ne ""} { set mode $v; break }
    }
  }

  switch -glob -- $mode {
    "write_only" - "w_only" - "write" - "writes" {
      dict set u USER_C_AXI_TEST_SELECT "write_only"
      if {![dict exists $u USER_C_AXI_NO_OF_WR_TRANS]} { dict set u USER_C_AXI_NO_OF_WR_TRANS 1 }
      dict set u USER_C_AXI_NO_OF_RD_TRANS 1
    }
    "read_only" - "r_only" - "read" - "reads" {
      dict set u USER_C_AXI_TEST_SELECT "read_only"
      if {![dict exists $u USER_C_AXI_NO_OF_RD_TRANS]} { dict set u USER_C_AXI_NO_OF_RD_TRANS 1 }
      dict set u USER_C_AXI_NO_OF_WR_TRANS 1
    }
    "wr_then_rd" - "writes_then_reads" - "sequential" - "seq" {
      dict set u USER_C_AXI_TEST_SELECT "writes_followed_by_reads"
      if {![dict exists $u USER_C_AXI_NO_OF_WR_TRANS]} { dict set u USER_C_AXI_NO_OF_WR_TRANS 1 }
      if {![dict exists $u USER_C_AXI_NO_OF_RD_TRANS]} { dict set u USER_C_AXI_NO_OF_RD_TRANS 1 }
    }
    "rw_parallel" - "parallel" {
      dict set u USER_C_AXI_TEST_SELECT "writes_and_reads_in_parallel"
      if {![dict exists $u USER_C_AXI_NO_OF_WR_TRANS]} { dict set u USER_C_AXI_NO_OF_WR_TRANS 1 }
      if {![dict exists $u USER_C_AXI_NO_OF_RD_TRANS]} { dict set u USER_C_AXI_NO_OF_RD_TRANS 1 }
    }
    default {
      dict set u USER_C_AXI_TEST_SELECT "write_read_interleaved"
      if {![dict exists $u USER_C_AXI_NO_OF_WR_TRANS]} { dict set u USER_C_AXI_NO_OF_WR_TRANS 1 }
    }
  }
  dict set u __tg_mode $mode
  return $u
}

proc _warn {id msg} {
    if {[llength [info commands send_msg_id]]} {
        send_msg_id $id WARNING $msg
    } else {
        puts stderr "WARNING: $id: $msg"
    }
}

proc _dict_get_list_or_empty {d k} {
    if {[dict exists $d $k]} {
        set v [dict get $d $k]
        # If someone provided a single dict instead of a list, wrap it.
        if {[catch {llength $v}] } {
            return [list $v]
        }
        return $v
    }
    return {}
}

proc _parse_hbm_settings {topo key} {
    if {[dict exists $topo hbm_endpoints]} {
        set explicit [dict get $topo hbm_endpoints]
        if {[llength $explicit] > 0} {
            set endpoints {}
            foreach entry $explicit {
                if {![dict exists $entry name]} {
                    error "Each hbm_endpoints entry must contain a name field."
                }
                set name [dict get $entry name]
                if {![regexp {^hbm([0-9]+)_port([0-3])$} $name -> ctrl port]} {
                    error "HBM endpoint '$name' must match hbm<controller>_port<0..3>."
                }
                lappend endpoints [dict create name $name]
            }
            return $endpoints
        }
    }

    # Get hbm_settings from topology dict
    if {![dict exists $topo $key]} {
        return {}
    }
    set hbm_settings [dict get $topo $key]

    # Get num_pc (number of pseudo-channels)
    if {![dict exists $hbm_settings num_pc]} {
        return {}
    }
    set num_pc [dict get $hbm_settings num_pc]

    # 2 ports per PC, 4 ports max per HBM controller
    set total_ports [expr {$num_pc * 2}]
    set ports_per_ctrl 4

    # Generate endpoint names
    set endpoints {}
    for {set p 0} {$p < $total_ports} {incr p} {
        set ctrl_num [expr {$p / $ports_per_ctrl}]
        set port_num [expr {$p % $ports_per_ctrl}]
        lappend endpoints [dict create name "hbm${ctrl_num}_port${port_num}"]
    }

    return $endpoints
}

# Parse DDR settings from topology JSON
# Returns: dict with num_mc, num_ports_per_mc, interleave_size_bytes
# Defaults: 1, 1, 128
proc _parse_ddr_settings {topo key} {
    set result [dict create num_mc 0 num_ports_per_mc 0 interleave_size_bytes 0]

    if {![dict exists $topo $key]} {
        return $result
    }
    set ddr_settings [dict get $topo $key]

    # Get DDR configuration values with defaults
    if {[dict exists $ddr_settings num_mc]} {
        dict set result num_mc [dict get $ddr_settings num_mc]
    }
    if {[dict exists $ddr_settings num_ports_per_mc]} {
        dict set result num_ports_per_mc [dict get $ddr_settings num_ports_per_mc]
    }
    if {[dict exists $ddr_settings interleave_size_bytes]} {
        dict set result interleave_size_bytes [dict get $ddr_settings interleave_size_bytes]
    }

    return $result
}
