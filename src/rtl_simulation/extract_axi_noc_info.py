#!/usr/bin/env python3
"""
Generate C++ path names for NoC modules from Verilator JSON output.

This script filters the module hierarchy to find paths ending in xpm_nsu_mm,
xpm_nmu_mm, xpm_nmu_strm, or xpm_nsu_strm, and outputs them in Verilator's
__DOT__ format for use in generated C++ code, including interface signal paths.
"""

import sys
import os
import argparse
from typing import List, Dict, Tuple, Set, Optional
from parse_verilator_json import parse_module_hierarchy, get_interface_variables


# Target leaf modules that we want to find paths to
TARGET_LEAF_MODULES: Set[str] = {
    'xpm_nsu_mm',
    'xpm_nmu_mm',
    'xpm_nmu_strm',
    'xpm_nsu_strm'
}

# AXIMM modules use ifc_axi interface
AXIMM_MODULES: Set[str] = {
    'xpm_nsu_mm',
    'xpm_nmu_mm'
}

# AXIS modules use ifc_axis interface
AXIS_MODULES: Set[str] = {
    'xpm_nmu_strm',
    'xpm_nsu_strm'
}

# Keep this metadata next to the hierarchy matcher.  It is the contract used by
# both the C++ wrapper generator and future gem5 configuration helpers: XPM
# naming tells us the protocol, the NoC-side role, and the port prefix exposed
# by the Verilated module.
ENDPOINT_MODULE_INFO = {
    "xpm_nmu_mm": {
        "protocol": "aximm",
        "role": "nmu",
        "signal_prefix": "s_axi_",
    },
    "xpm_nsu_mm": {
        "protocol": "aximm",
        "role": "nsu",
        "signal_prefix": "m_axi_",
    },
    "xpm_nmu_strm": {
        "protocol": "axis",
        "role": "nmu",
        "signal_prefix": "s_axis_",
    },
    "xpm_nsu_strm": {
        "protocol": "axis",
        "role": "nsu",
        "signal_prefix": "m_axis_",
    },
}


def canonical_module_type(module_type: str) -> str:
    """Remove Verilator's parameter-specialization suffix from a module type."""
    return module_type.split("__", 1)[0]


def find_paths_to_target_modules(
    hierarchy: Dict[str, List[Tuple[str, str]]],
    root_module: str
) -> List[List[str]]:
    """
    Find all paths from a root module to target leaf modules.
    
    Args:
        hierarchy: Dictionary mapping module names to their child instantiations
        root_module: Root module name to start traversal from
        
    Returns:
        List of paths, where each path is a list of instance names from root to leaf
    """
    all_paths: List[List[str]] = []
    
    def traverse_module(
        module_name: str,
        current_path: List[str],
        visited_modules: Set[str]
    ):
        """Recursively traverse the hierarchy to find paths to target modules."""
        # Check if this is a target leaf module
        if canonical_module_type(module_name) in TARGET_LEAF_MODULES:
            all_paths.append(current_path[:])
            return
        
        # Prevent infinite loops (though shouldn't happen in normal designs)
        if module_name in visited_modules:
            return
        
        visited_modules.add(module_name)
        
        # Get children of this module
        children = hierarchy.get(module_name, [])
        for instance_name, child_module_name in children:
            # Add this instance to the path
            current_path.append(instance_name)
            # Recursively traverse the child
            traverse_module(child_module_name, current_path, visited_modules.copy())
            # Backtrack
            current_path.pop()
    
    # Start traversal from root module
    traverse_module(root_module, [], set())
    
    return all_paths


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


def find_paths_to_target_modules_with_types(
    hierarchy: Dict[str, List[Tuple[str, str]]],
    root_module: str
) -> List[Tuple[List[str], str]]:
    """
    Find all paths from a root module to target leaf modules, returning both
    the path and the target module type.
    
    Args:
        hierarchy: Dictionary mapping module names to their child instantiations
        root_module: Root module name to start traversal from
        
    Returns:
        List of (path, module_type) tuples, where path is a list of instance names
        and module_type is the target leaf module type
    """
    all_paths: List[Tuple[List[str], str]] = []
    
    def traverse_module(
        module_name: str,
        current_path: List[str],
        visited_modules: Set[str]
    ):
        """Recursively traverse the hierarchy to find paths to target modules."""
        # Check if this is a target leaf module
        canonical_type = canonical_module_type(module_name)
        if canonical_type in TARGET_LEAF_MODULES:
            all_paths.append((current_path[:], canonical_type))
            return
        
        # Prevent infinite loops (though shouldn't happen in normal designs)
        if module_name in visited_modules:
            return
        
        visited_modules.add(module_name)
        
        # Get children of this module
        children = hierarchy.get(module_name, [])
        for instance_name, child_module_name in children:
            # Add this instance to the path
            current_path.append(instance_name)
            # Recursively traverse the child
            traverse_module(child_module_name, current_path, visited_modules.copy())
            # Backtrack
            current_path.pop()
    
    # Start traversal from root module
    traverse_module(root_module, [], set())
    
    return all_paths


def find_root_module(hierarchy: Dict[str, List[Tuple[str, str]]]) -> str:
    """Return the top-level module represented by a Verilator hierarchy."""
    all_child_modules = {
        module_type
        for children in hierarchy.values()
        for _, module_type in children
    }
    root_modules = [
        module_name
        for module_name in hierarchy
        if module_name not in all_child_modules
    ]
    if root_modules:
        return root_modules[0]
    return next(iter(hierarchy), "")


def discover_noc_endpoints(json_file: str) -> List[Dict[str, str]]:
    """Discover XPM NoC endpoints and return a stable machine-readable map.

    The returned descriptors deliberately contain no gem5 object names.  A
    design manifest/configuration owns that policy, while this discovery phase
    reports only facts available from the RTL hierarchy.
    """
    hierarchy = parse_module_hierarchy(json_file)
    if not hierarchy:
        return []

    root_module = find_root_module(hierarchy)
    endpoints = []
    endpoint_counts = {}
    for path, module_type in find_paths_to_target_modules_with_types(
        hierarchy, root_module
    ):
        info = ENDPOINT_MODULE_INFO[module_type]
        endpoint_kind = (info["role"], info["protocol"])
        index = endpoint_counts.get(endpoint_kind, 0)
        endpoint_counts[endpoint_kind] = index + 1
        instance_path = ".".join(path)
        endpoints.append(
            {
                "id": f"{info['role']}_{info['protocol']}_{index}",
                "instance_path": instance_path,
                "verilator_path": format_path_as_cpp_name(root_module, path),
                "module_type": module_type,
                "protocol": info["protocol"],
                "role": info["role"],
                "signal_prefix": info["signal_prefix"],
            }
        )
    return endpoints


def generate_noc_paths(json_file: str) -> List[str]:
    """
    Parse Verilator JSON and generate C++ path names for target NoC modules.
    Includes interface signal paths appended to module instance paths.
    
    Args:
        json_file: Path to Verilator JSON file
        
    Returns:
        List of formatted C++ path strings, including module paths and interface signal paths
    """
    # Parse the hierarchy
    hierarchy = parse_module_hierarchy(json_file)
    
    if not hierarchy:
        return []
    
    # Get interface definitions
    interfaces = get_interface_variables(json_file)
    
    # Map interface names to their logic signals
    interface_signals: Dict[str, List[str]] = {}
    for ifc_name, ifc_data in interfaces.items():
        # Get all logic signal names (not parameters)
        signal_names = [var['name'] for var in ifc_data['logics']]
        interface_signals[ifc_name] = signal_names
    
    # Determine which interface to use for each module type
    # Note: Interface names in Verilator might be 'ifc_axi' or 'ifc_axis'
    aximm_interface_name = None
    axis_interface_name = None
    
    for ifc_name in interfaces.keys():
        if 'axi' in ifc_name.lower() and 'axis' not in ifc_name.lower():
            aximm_interface_name = ifc_name
        elif 'axis' in ifc_name.lower():
            axis_interface_name = ifc_name
    
    # Find root modules (modules that are not instantiated anywhere)
    all_child_modules = set()
    for children in hierarchy.values():
        for _, module_type in children:
            all_child_modules.add(module_type)
    
    root_modules = [name for name in hierarchy.keys() if name not in all_child_modules]
    
    # If we can't find root modules this way, just use the first module
    if not root_modules:
        root_modules = [list(hierarchy.keys())[0]] if hierarchy else []
    
    # Find all paths to target modules and format them with interface signals
    cpp_paths = []
    for root_module in root_modules:
        paths_with_types = find_paths_to_target_modules_with_types(hierarchy, root_module)
        for path, module_type in paths_with_types:
            # Format the base path
            base_path = format_path_as_cpp_name(root_module, path)
            
            # Determine which interface to use based on module type
            interface_name = None
            if module_type in AXIMM_MODULES and aximm_interface_name:
                interface_name = aximm_interface_name
            elif module_type in AXIS_MODULES and axis_interface_name:
                interface_name = axis_interface_name
            
            # Append interface signals if we found the interface
            if interface_name and interface_name in interface_signals:
                signals = interface_signals[interface_name]
                for signal_name in signals:
                    signal_path = f"{base_path}__DOT__{signal_name}"
                    cpp_paths.append(signal_path)
            else:
                # If no interface found, still add the base path
                cpp_paths.append(base_path)
    
    return cpp_paths


def parse_args():
    """
    Parse command-line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Generate C++ path names for NoC modules from Verilator JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s obj_dir/top.tree.json
  %(prog)s /path/to/Vtest_module.tree.json
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
        help="Output file (default: print to stdout)"
    )
    
    return parser.parse_args()


def main():
    """
    Main entry point - parse JSON and generate C++ path names.
    """
    args = parse_args()
    json_file = args.json_file
    
    # Check if file exists
    if not os.path.exists(json_file):
        print(f"Error: JSON file not found: {json_file}", file=sys.stderr)
        return 1
    
    try:
        cpp_paths = generate_noc_paths(json_file)
        
        # Sort for consistent output
        cpp_paths.sort()
        
        # Output the paths
        output_lines = cpp_paths
        
        if args.output:
            with open(args.output, 'w') as f:
                for path in output_lines:
                    f.write(path + '\n')
        else:
            for path in output_lines:
                print(path)
        
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
