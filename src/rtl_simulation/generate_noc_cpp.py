#!/usr/bin/env python3
"""
Generate C++ traits structs for NoC module signals from Verilator JSON output.

This script generates traits structs (one per NMU/NSU instance) that provide
compile-time accessors for signal references in the Verilator DUT hierarchy.
"""

import sys
import os
import json
import argparse
from typing import List, Dict, Set, Tuple, Optional
from extract_axi_noc_info import (
    AXIMM_MODULES,
    AXIS_MODULES,
    ENDPOINT_MODULE_INFO,
    discover_noc_endpoints,
    find_paths_to_target_modules_with_types,
    find_root_module,
    parse_module_hierarchy,
)
from parse_verilator_json import get_interface_variables


# Signal names for AXIS interface
AXIS_SIGNALS = [
    'tdata', 'tkeep', 'tid', 'tdest', 'tlast', 'tvalid', 'tready'
]

# Signal names for AXIMM interface (all channels)
AXIMM_SIGNALS = [
    # AW channel
    's_axi_awaddr', 's_axi_awlen', 's_axi_awsize', 's_axi_awburst',
    's_axi_awprot', 's_axi_awcache', 's_axi_awid', 's_axi_awlock',
    's_axi_awqos', 's_axi_awregion', 's_axi_awuser', 's_axi_awvalid', 's_axi_awready',
    # W channel
    's_axi_wdata', 's_axi_wstrb', 's_axi_wuser', 's_axi_wid',
    's_axi_wlast', 's_axi_wvalid', 's_axi_wready',
    # B channel
    's_axi_bresp', 's_axi_bid', 's_axi_buser', 's_axi_bvalid', 's_axi_bready',
    # AR channel
    's_axi_araddr', 's_axi_arlen', 's_axi_arsize', 's_axi_arburst',
    's_axi_arprot', 's_axi_arcache', 's_axi_arid', 's_axi_arlock',
    's_axi_arqos', 's_axi_arregion', 's_axi_aruser', 's_axi_arvalid', 's_axi_arready',
    # R channel
    's_axi_rdata', 's_axi_rresp', 's_axi_rid', 's_axi_ruser',
    's_axi_rlast', 's_axi_rvalid', 's_axi_rready'
]


def signals_for_module(module_type: str) -> List[str]:
    """Return Verilator-visible signal names for one XPM endpoint type."""
    info = ENDPOINT_MODULE_INFO[module_type]
    base_signals = AXIS_SIGNALS if info["protocol"] == "axis" else AXIMM_SIGNALS
    # AXIMM_SIGNALS predates direction-aware discovery and is expressed with
    # the NMU s_axi_ prefix.  Normalize to bare channel names before applying
    # the endpoint's actual Verilator port prefix.
    return [
        info["signal_prefix"]
        + (signal[6:] if signal.startswith("s_axi_") else signal)
        for signal in base_signals
    ]


def format_path_as_cpp_name(top_module_name: str, instance_path: List[str]) -> str:
    """
    Format a module path as a Verilator C++ name using __DOT__ separators.
    
    Args:
        top_module_name: Name of the top-level module
        instance_path: List of instance names from top to leaf (excluding top module)
        
    Returns:
        Formatted string like: top_module__DOT__inst1__DOT__inst2
    """
    parts = [top_module_name] + instance_path
    return '__DOT__'.join(parts)


def generate_trait_struct_name(full_path: str, module_type: str) -> str:
    """
    Generate a trait struct name based on full hierarchical path and module type.
    
    Args:
        full_path: Full hierarchical path with __DOT__ separators (e.g., 'test_all_noc__DOT__u_nmu_strm')
        module_type: Type of module (xpm_nmu_mm, xpm_nsu_strm, etc.)
        
    Returns:
        Trait struct name (e.g., 'Axis_test_all_noc__DOT__u_nmu_strmTraits', 'Axi_test_all_noc__DOT__u_nmu_mmTraits')
    """
    # Determine prefix based on module type
    if module_type in AXIS_MODULES:
        prefix = 'Axis'
    elif module_type in AXIMM_MODULES:
        prefix = 'Axi'
    else:
        prefix = 'Unknown'
    
    # Use the full path with __DOT__ separators as-is
    # The path is already a valid C++ identifier format
    # Add underscore between prefix and path
    return f"{prefix}_{full_path}Traits"


def generate_trait_struct(
    struct_name: str,
    base_path: str,
    signals: List[str],
    signal_prefix: str = ''
) -> str:
    """
    Generate a C++ traits struct with signal accessor methods.
    
    Args:
        struct_name: Name of the traits struct
        base_path: Base path to the instance (e.g., 'test_all_noc__DOT__u_nmu_strm')
        signals: List of signal names (with prefix if needed, e.g., 's_axi_awaddr' or 'tdata')
        signal_prefix: Not used (kept for compatibility)
        
    Returns:
        C++ code for the traits struct
    """
    lines = []
    lines.append(f"struct {struct_name} {{")
    
    # Generate accessor method for each signal
    for signal_name in signals:
        # The signal_path uses the full signal name (e.g., s_axi_awaddr or tdata)
        signal_path = f"{base_path}__DOT__{signal_name}"
        
        # Generate method name: 
        # Both NMU and NSU endpoints use the same trait method names.  Their
        # Verilator-visible ports differ only in the direction-specific prefix.
        for prefix in ('s_axi_', 'm_axi_', 's_axis_', 'm_axis_'):
            if signal_name.startswith(prefix):
                method_name = signal_name[len(prefix):] + '_ref'
                break
        else:
            method_name = signal_name + '_ref'
        
        lines.append(f"\ttemplate <typename RootT> static constexpr auto& {method_name}(RootT& r) {{ return r.{signal_path}; }}")
    
    lines.append("};")
    lines.append("")
    
    return '\n'.join(lines)


def extract_prefix_from_json_file(json_file: str) -> str:
    """
    Extract the design prefix from the JSON filename.
    
    Args:
        json_file: Path to Verilator JSON file (e.g., "obj_dir/top.tree.json")
        
    Returns:
        Prefix name (e.g., "top" from "top.tree.json")
    """
    # Get just the filename
    filename = os.path.basename(json_file)
    # Remove .tree.json extension
    if filename.endswith('.tree.json'):
        prefix = filename[:-10]  # Remove '.tree.json'
    elif filename.endswith('.json'):
        prefix = filename[:-5]  # Remove '.json'
    else:
        prefix = filename
    return prefix


def generate_wrapper_class(
    json_file: str,
    prefix: str = None
) -> str:
    """
    Generate C++ wrapper class file with all NMU/NSU instances.
    
    Args:
        json_file: Path to Verilator JSON file
        prefix: Design prefix name (if None, extracted from json_file)
        
    Returns:
        C++ code for the wrapper class file as a string
    """
    if prefix is None:
        prefix = extract_prefix_from_json_file(json_file)
    
    # Calculate root class name from prefix
    root_class_name = f"{prefix}___024root"
    
    # Parse the hierarchy
    hierarchy = parse_module_hierarchy(json_file)
    
    if not hierarchy:
        return ""
    
    root_module = find_root_module(hierarchy)
    
    # Find all instances of target modules
    paths_with_types = find_paths_to_target_modules_with_types(hierarchy, root_module)
    
    if not paths_with_types:
        return ""
    
    # Generate header file name
    header_name = f"{prefix}.h"
    root_header_name = f"{prefix}___024root.h"
    mappings_name = f"{prefix}_verilator_mappings.h"
    namespace_name = f"{prefix}_verilator"
    
    # Generate wrapper class
    lines = []
    lines.append(f'#include "{root_header_name}"')
    lines.append(f'#include "{mappings_name}"')
    lines.append('#include "noc_rtl_bridge.h"')
    lines.append('#include <vector>')
    lines.append('#include <cstddef>')
    lines.append('')
    lines.append(f'namespace {namespace_name} {{')
    lines.append('')
    lines.append('class NocConnections {')
    lines.append('public:')
    lines.append(f'    {root_class_name}* root_;')
    lines.append('')
    lines.append('    // Vectors containing all port bindings (created in constructor)')
    lines.append(f'    std::vector<AxisPortBinding<{root_class_name}>> axis_bindings_;')
    lines.append(f'    std::vector<AxiPortBinding<{root_class_name}>> axi_bindings_;')
    lines.append('')
    
    # Collect all bindings info first (needed for constructor and pack/unpack methods)
    instance_bindings = []
    axis_traits = []
    axi_traits = []
    for path, module_type in paths_with_types:
        # Format the base path and generate traits struct name using full hierarchical path
        base_path = format_path_as_cpp_name(root_module, path)
        traits_name = generate_trait_struct_name(base_path, module_type)
        
        # Determine binding type
        if module_type in AXIS_MODULES:
            binding_type = 'AxisPortBinding'
            axis_traits.append(traits_name)
        elif module_type in AXIMM_MODULES:
            binding_type = 'AxiPortBinding'
            axi_traits.append(traits_name)
        else:
            binding_type = 'UnknownBinding'
        
        instance_bindings.append((binding_type, traits_name))
    
    lines.append(f'    explicit NocConnections({root_class_name}* root)')
    lines.append(f'        : root_(root)')
    lines.append('    {')
    
    # Create objects directly in the vectors
    for binding_type, traits_name in instance_bindings:
        if binding_type == 'AxisPortBinding':
            lines.append(f'        axis_bindings_.emplace_back(root, {namespace_name}::{traits_name}{{}});')
        elif binding_type == 'AxiPortBinding':
            lines.append(f'        axi_bindings_.emplace_back(root, {namespace_name}::{traits_name}{{}});')
    
    lines.append('    }')
    lines.append('')
    lines.append('    // Typical cycle discipline:')
    lines.append('    // 1) User updates shadow structs via vectors (e.g., axis_bindings_[0].shadow.tdata[0] = 0x1234)')
    lines.append('    //    Or use convenience method: axis_bindings_[0].view().tdata[0] = 0x1234')
    lines.append('    // 2) pack_all_inputs()  // Copies shadow values to DUT signals')
    lines.append('    // 3) dut->eval()         // Run simulation cycle')
    lines.append('    // 4) unpack_all_outputs() // Copies DUT outputs to shadow structs')
    lines.append('    // 5) Read results from shadow (e.g., bool ready = axis_bindings_[0].shadow.tready)')
    lines.append('    inline void pack_all_inputs() noexcept {')
    
    # Generate pack_all_inputs() calls explicitly with indices
    axis_index = 0
    axi_index = 0
    for binding_type, traits_name in instance_bindings:
        if binding_type == 'AxisPortBinding':
            lines.append(f'        axis_bindings_[{axis_index}].pack_to_dut({namespace_name}::{traits_name}{{}});')
            axis_index += 1
        elif binding_type == 'AxiPortBinding':
            lines.append(f'        axi_bindings_[{axi_index}].pack_to_dut({namespace_name}::{traits_name}{{}});')
            axi_index += 1
    
    lines.append('    }')
    lines.append('')
    lines.append('    inline void unpack_all_outputs() noexcept {')
    
    # Generate unpack_all_outputs() calls explicitly with indices
    axis_index = 0
    axi_index = 0
    for binding_type, traits_name in instance_bindings:
        if binding_type == 'AxisPortBinding':
            lines.append(f'        axis_bindings_[{axis_index}].unpack_from_dut({namespace_name}::{traits_name}{{}});')
            axis_index += 1
        elif binding_type == 'AxiPortBinding':
            lines.append(f'        axi_bindings_[{axi_index}].unpack_from_dut({namespace_name}::{traits_name}{{}});')
            axi_index += 1
    
    lines.append('    }')
    lines.append('};')
    lines.append('')
    lines.append(f'}} // namespace {namespace_name}')
    lines.append('')
    
    return '\n'.join(lines)


def generate_rtl_mappings(
    json_file: str,
    prefix: str = None
) -> str:
    """
    Generate C++ traits structs for all NMU/NSU instances in the design.
    
    Args:
        json_file: Path to Verilator JSON file
        prefix: Design prefix name (if None, extracted from json_file)
        
    Returns:
        C++ code for <prefix>_verilator_mappings.h as a string
    """
    if prefix is None:
        prefix = extract_prefix_from_json_file(json_file)
    
    # Calculate root class name from prefix
    root_class_name = f"{prefix}___024root"
    root_header_name = f"{prefix}___024root.h"
    namespace_name = f"{prefix}_verilator"
    
    # Parse the hierarchy
    hierarchy = parse_module_hierarchy(json_file)
    
    if not hierarchy:
        return ""
    
    # Get interface definitions
    interfaces = get_interface_variables(json_file)
    
    # Find root module
    all_child_modules = set()
    for children in hierarchy.values():
        for _, module_type in children:
            all_child_modules.add(module_type)
    root_modules = [name for name in hierarchy.keys() if name not in all_child_modules]
    if not root_modules:
        root_modules = [list(hierarchy.keys())[0]] if hierarchy else []
    root_module = root_modules[0] if root_modules else ""
    
    # Find all instances of target modules
    paths_with_types = find_paths_to_target_modules_with_types(hierarchy, root_module)
    
    # Generate header
    header_guard = f'{prefix.upper()}_VERILATOR_MAPPINGS_H'
    lines = []
    lines.append(f'#ifndef {header_guard}')
    lines.append(f'#define {header_guard}')
    lines.append('')
    lines.append(f'#include "{root_header_name}"')
    lines.append('')
    lines.append(f'namespace {namespace_name} {{')
    lines.append('')
    
    # Track which interface types we've seen to add comments only once
    seen_axis = False
    seen_aximm = False
    
    # Generate traits struct for each instance
    for path, module_type in paths_with_types:
        # Format the base path
        base_path = format_path_as_cpp_name(root_module, path)
        
        # Generate struct name using the full hierarchical path
        struct_name = generate_trait_struct_name(base_path, module_type)
        
        # Determine which signals to use based on module type
        if module_type in AXIS_MODULES:
            signals = signals_for_module(module_type)
            # Add comment before first AXIS struct
            if not seen_axis:
                lines.append("// AXIS hierarchy traits: provide accessors for each signal reference.")
                lines.append("// This avoids hardcoding member types in the binding class and keeps binding clean.")
                seen_axis = True
        elif module_type in AXIMM_MODULES:
            signals = signals_for_module(module_type)
            # Add comment before first AXIMM struct
            if not seen_aximm:
                lines.append("// AXI hierarchy traits: provide accessors for each signal reference.")
                lines.append("// This avoids hardcoding member types in the binding class and keeps binding clean.")
                seen_aximm = True
        else:
            signals = []
        
        # Generate the traits struct
        trait_code = generate_trait_struct(struct_name, base_path, signals)
        lines.append(trait_code)
    
    lines.append(f'}} // namespace {namespace_name}')
    lines.append('')
    lines.append(f'#endif // {header_guard}')
    lines.append('')
    
    return '\n'.join(lines)


def generate_endpoint_map(json_file: str, prefix: str = None) -> Dict[str, object]:
    """Create the checked, tool-neutral endpoint map for one RTL design."""
    if prefix is None:
        prefix = extract_prefix_from_json_file(json_file)
    hierarchy = parse_module_hierarchy(json_file)
    return {
        "schema_version": 1,
        "design": prefix,
        "top_module": find_root_module(hierarchy),
        "endpoints": discover_noc_endpoints(json_file),
    }


def parse_args():
    """
    Parse command-line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Generate C++ traits structs for NoC module signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s obj_dir/top.tree.json
        %(prog)s obj_dir/top.tree.json -o rtl_mappings.h
        """
    )
    
    parser.add_argument(
        "json_file",
        type=str,
        help="Path to Verilator JSON file (e.g., obj_dir/top.tree.json)"
    )
    
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output file for mappings (default: <prefix>_verilator_mappings.h)"
    )
    
    parser.add_argument(
        "--wrapper-output",
        type=str,
        default=None,
        help="Output file for wrapper class (default: <prefix>_verilator.h in same dir as mappings file)"
    )
    
    parser.add_argument(
        "--prefix",
        type=str,
        default=None,
        help="Design prefix name (default: extracted from JSON filename)"
    )
    parser.add_argument(
        "--endpoint-map-output",
        type=str,
        default=None,
        help="Write discovered XPM endpoints as deterministic JSON",
    )
    
    return parser.parse_args()


def main():
    """
    Main entry point - generate C++ traits structs.
    """
    args = parse_args()
    json_file = args.json_file
    
    # Check if file exists
    if not os.path.exists(json_file):
        print(f"Error: JSON file not found: {json_file}", file=sys.stderr)
        return 1
    
    try:
        # Extract or use provided prefix
        prefix = args.prefix
        if prefix is None:
            prefix = extract_prefix_from_json_file(json_file)
        
        # Determine output filename
        if args.output:
            mappings_output = args.output
        else:
            # Default: <prefix>_verilator_mappings.h
            mappings_output = f"{prefix}_verilator_mappings.h"
        
        cpp_code = generate_rtl_mappings(
            json_file,
            prefix=prefix
        )
        
        if not cpp_code:
            print("Error: No signals found to generate", file=sys.stderr)
            return 1
        
        # Write to output file
        with open(mappings_output, 'w') as f:
            f.write(cpp_code)
        
        print(f"Generated traits structs written to {mappings_output}")
        
        # Always generate wrapper class
        wrapper_code = generate_wrapper_class(
            json_file,
            prefix=prefix
        )
        
        if wrapper_code:
            if args.wrapper_output:
                wrapper_path = args.wrapper_output
            else:
                # Default: <prefix>_verilator.h in same directory as mappings file
                output_dir = os.path.dirname(mappings_output) or '.'
                wrapper_filename = f"{prefix}_verilator.h"
                wrapper_path = os.path.join(output_dir, wrapper_filename)
            
            with open(wrapper_path, 'w') as f:
                f.write(wrapper_code)
            print(f"Generated wrapper class written to {wrapper_path}")
        else:
            print("Warning: No instances found to generate wrapper class", file=sys.stderr)

        if args.endpoint_map_output:
            with open(args.endpoint_map_output, 'w', encoding='utf-8') as f:
                json.dump(generate_endpoint_map(json_file, prefix), f, indent=2)
                f.write('\n')
            print(f"Generated endpoint map written to {args.endpoint_map_output}")

        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
