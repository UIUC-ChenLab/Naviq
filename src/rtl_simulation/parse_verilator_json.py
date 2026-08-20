#!/usr/bin/env python3
"""
Generate C++ code from SystemVerilog modules using Verilator JSON output.

This module provides functionality to run Verilator with --json-only flag
to generate JSON representation of SystemVerilog designs for further processing.
"""

import subprocess
import os
import sys
import json
from pathlib import Path
from typing import List, Optional, Set, Dict, Tuple
import re


def parse_module_hierarchy(json_file: str) -> Dict[str, List[Tuple[str, str]]]:
    """
    Parse a Verilator JSON file and extract the module hierarchy.
    
    Args:
        json_file: Path to the Verilator JSON file (e.g., top.tree.json)
        
    Returns:
        Dictionary mapping module names to lists of (instance_name, module_type) tuples
        representing child instantiations. The hierarchy is built from this data.
    """
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    # Build mapping from module address to module name
    module_addr_to_name: Dict[str, str] = {}
    modules = data.get('modulesp', [])
    
    for module in modules:
        if module.get('type') == 'MODULE':
            addr = module.get('addr')
            name = module.get('name')
            if addr and name:
                module_addr_to_name[addr] = name
    
    # Build hierarchy: for each module, find its child instantiations
    hierarchy: Dict[str, List[Tuple[str, str]]] = {}
    
    for module in modules:
        if module.get('type') != 'MODULE':
            continue
            
        module_name = module.get('name')
        if not module_name:
            continue
            
        hierarchy[module_name] = []
        stmts = module.get('stmtsp', [])
        
        for stmt in stmts:
            if stmt.get('type') == 'CELL':
                instance_name = stmt.get('name')
                modp = stmt.get('modp')  # Address pointer to the module definition
                
                if instance_name and modp and modp in module_addr_to_name:
                    instantiated_module = module_addr_to_name[modp]
                    hierarchy[module_name].append((instance_name, instantiated_module))
    
    return hierarchy


def print_module_hierarchy(json_file: str):
    """
    Parse a Verilator JSON file and print the module hierarchy cleanly to the terminal,
    including input and output signals for each module.
    
    Args:
        json_file: Path to the Verilator JSON file (e.g., top.tree.json)
    """
    hierarchy = parse_module_hierarchy(json_file)
    
    if not hierarchy:
        print("No module hierarchy found in JSON file.")
        return
    
    # Collect all unique module names from the hierarchy
    all_module_names = set(hierarchy.keys())
    for children in hierarchy.values():
        for _, module_type in children:
            all_module_names.add(module_type)
    
    # Build mapping from module name to origName
    with open(json_file, 'r') as f:
        data = json.load(f)
    module_name_to_orig: Dict[str, str] = {}
    modules = data.get('modulesp', [])
    for module in modules:
        if module.get('type') == 'MODULE':
            name = module.get('name')
            orig_name = module.get('origName')
            if name and orig_name:
                module_name_to_orig[name] = orig_name
    
    # Get signal information for all modules
    module_signals = get_module_signals(json_file, list(all_module_names))
    
    # Get interface information for showing interface signals
    interface_vars = get_interface_variables(json_file)
    
    # Get interface instances to find which interfaces each module uses
    interface_instances = parse_interface_instances(json_file)
    
    def format_module_name(module_name: str) -> str:
        """Format module name showing origName if different from name."""
        orig_name = module_name_to_orig.get(module_name)
        if orig_name and orig_name != module_name:
            return f"{module_name} ({orig_name})"
        return module_name
    
    def print_signals(module_name: str, prefix: str):
        """Print input and output signals for a module."""
        signals = module_signals.get(module_name, {})
        if signals:
            # Print regular ports
            inputs = []
            outputs = []
            inouts = []
            
            for signal_name, signal_info in signals.items():
                direction = signal_info.get('direction', 'NONE')
                width = signal_info.get('width')
                if width is not None and width > 1:
                    width_str = f"[{width-1}:0]"
                else:
                    width_str = ""
                signal_str = f"{signal_name}{width_str}"
                
                if direction == 'INPUT':
                    inputs.append(signal_str)
                elif direction == 'OUTPUT':
                    outputs.append(signal_str)
                elif direction == 'INOUT':
                    inouts.append(signal_str)
            
            if inputs:
                print(f"{prefix}  Inputs: {', '.join(inputs)}")
            if outputs:
                print(f"{prefix}  Outputs: {', '.join(outputs)}")
            if inouts:
                print(f"{prefix}  Inouts: {', '.join(inouts)}")
        
        # Also check for interface signals
        module_interfaces = interface_instances.get(module_name, [])
        for ifc_instance_name, ifc_type_name in module_interfaces:
            # Get interface signals from interface definition
            ifc_data = interface_vars.get(ifc_type_name)
            if ifc_data:
                logics = ifc_data.get('logics', [])
                if logics:
                    # Separate by direction
                    ifc_inputs = []
                    ifc_outputs = []
                    ifc_inouts = []
                    for logic in logics:
                        direction = logic.get('direction')
                        name = logic.get('name', '')
                        width = logic.get('width')
                        if width is not None and width > 1:
                            width_str = f"[{width-1}:0]"
                        else:
                            width_str = ""
                        signal_str = f"{name}{width_str}"
                        
                        if direction == 'INPUT':
                            ifc_inputs.append(signal_str)
                        elif direction == 'OUTPUT':
                            ifc_outputs.append(signal_str)
                        elif direction == 'INOUT':
                            ifc_inouts.append(signal_str)
                    
                    # Print interface signals
                    if ifc_inputs or ifc_outputs or ifc_inouts:
                        print(f"{prefix}  Interface {ifc_instance_name} ({ifc_type_name}):")
                        if ifc_inputs:
                            print(f"{prefix}    Inputs: {', '.join(ifc_inputs)}")
                        if ifc_outputs:
                            print(f"{prefix}    Outputs: {', '.join(ifc_outputs)}")
                        if ifc_inouts:
                            print(f"{prefix}    Inouts: {', '.join(ifc_inouts)}")
        
        # Also check for interface references (VARs with IFACEREF type) in the module
        # These are interfaces declared as ports/parameters in the module
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        # Build mapping from dtypep to interface name using typetable
        dtypep_to_ifc_name = {}
        miscsp = data.get('miscsp', [])
        for item in miscsp:
            if item.get('type') == 'TYPETABLE':
                typesp = item.get('typesp', [])
                for type_entry in typesp:
                    if type_entry.get('type') == 'IFACEREFDTYPE':
                        dtypep_addr = type_entry.get('addr')
                        iface_name = type_entry.get('ifaceName', '')
                        if dtypep_addr and iface_name:
                            dtypep_to_ifc_name[dtypep_addr] = iface_name
        
        modules = data.get('modulesp', [])
        for module in modules:
            if module.get('type') == 'MODULE' and module.get('name') == module_name:
                stmts = module.get('stmtsp', [])
                
                # Find IFACEREF VARs
                for stmt in stmts:
                    if stmt.get('type') == 'VAR' and stmt.get('varType') == 'IFACEREF':
                        ifc_var_name = stmt.get('name', '')
                        dtypep = stmt.get('dtypep')
                        
                        # Look up the interface name from the typetable
                        ifc_type_name = dtypep_to_ifc_name.get(dtypep) if dtypep else None
                        
                        if ifc_type_name and ifc_type_name in interface_vars:
                            # Get the correct interface data
                            ifc_data = interface_vars[ifc_type_name]
                            logics = ifc_data.get('logics', [])
                            if logics:
                                # Collect all interface signals (interfaces don't have direction)
                                ifc_signals = []
                                for logic in logics:
                                    name = logic.get('name', '')
                                    width = logic.get('width')
                                    if width is not None and width > 1:
                                        width_str = f"[{width-1}:0]"
                                    else:
                                        width_str = ""
                                    signal_str = f"{name}{width_str}"
                                    ifc_signals.append(signal_str)
                                
                                # Print interface signals
                                if ifc_signals:
                                    print(f"{prefix}  Interface {ifc_var_name} ({ifc_type_name}):")
                                    # Show first 10 signals to avoid overwhelming output
                                    signals_to_show = ifc_signals[:10]
                                    print(f"{prefix}    Signals: {', '.join(signals_to_show)}")
                                    if len(ifc_signals) > 10:
                                        print(f"{prefix}    ... and {len(ifc_signals) - 10} more")
                break
    
    def print_instance_tree(instance_name: str, module_name: str, prefix: str = "", is_last: bool = True):
        """Recursively print instance hierarchy tree."""
        # Print instance name and module type
        connector = "└── " if is_last else "├── "
        formatted_module_name = format_module_name(module_name)
        print(f"{prefix}{connector}{instance_name} ({formatted_module_name})")
        
        # Print signals for this module
        signal_prefix = prefix + ("    " if is_last else "│   ")
        print_signals(module_name, signal_prefix)
        
        # Update prefix for children
        child_prefix = prefix + ("    " if is_last else "│   ")
        
        # Get children of this module
        children = hierarchy.get(module_name, [])
        for idx, (child_instance_name, child_module_name) in enumerate(children):
            is_last_child = (idx == len(children) - 1)
            # Recursively print child instances
            print_instance_tree(child_instance_name, child_module_name, child_prefix, is_last_child)
    
    # Find root modules (modules that are not instantiated anywhere)
    # In Verilator JSON, the top module is typically the one with the lowest level
    # or we can find modules that aren't referenced as children
    all_child_modules = set()
    for children in hierarchy.values():
        for _, module_type in children:
            all_child_modules.add(module_type)
    
    # Root modules are those that exist in hierarchy but aren't children
    root_modules = [name for name in hierarchy.keys() if name not in all_child_modules]
    
    # If we can't find root modules this way, just use the first module
    if not root_modules:
        root_modules = [list(hierarchy.keys())[0]] if hierarchy else []
    
    # Print all root modules
    for idx, root_module in enumerate(root_modules):
        is_last_root = (idx == len(root_modules) - 1)
        # Print root module name
        connector = "└── " if is_last_root else "├── "
        formatted_root_name = format_module_name(root_module)
        print(f"{connector}{formatted_root_name}")
        
        # Print signals for root module
        root_prefix = "    " if is_last_root else "│   "
        print_signals(root_module, root_prefix)
        
        # Print children of root module
        children = hierarchy.get(root_module, [])
        child_prefix = "    " if is_last_root else "│   "
        for child_idx, (instance_name, module_name) in enumerate(children):
            is_last_child = (child_idx == len(children) - 1)
            print_instance_tree(instance_name, module_name, child_prefix, is_last_child)
        
        # Print separator between multiple root modules
        if idx < len(root_modules) - 1:
            print()


def parse_interface_definitions(json_file: str) -> Dict[str, Dict]:
    """
    Parse a Verilator JSON file and extract all interface definitions.
    
    In Verilator, interfaces are represented as type "IFACE" in the JSON structure.
    
    Args:
        json_file: Path to the Verilator JSON file (e.g., top.tree.json)
        
    Returns:
        Dictionary mapping interface names to their definitions, where each definition
        contains 'name', 'variables' (list of logic variable info dicts), and 'parameters'
        (list of parameter variable info dicts)
    """
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    interfaces: Dict[str, Dict] = {}
    modules = data.get('modulesp', [])
    
    # Extract interface definitions - interfaces are type "IFACE" in Verilator
    for module in modules:
        if module.get('type') != 'IFACE':
            continue
        
        interface_name = module.get('name')
        if not interface_name:
            continue
        
        interfaces[interface_name] = {
            'name': interface_name,
            'variables': [],
            'parameters': []
        }
        
        stmts = module.get('stmtsp', [])
        for stmt in stmts:
            if stmt.get('type') == 'VAR':
                var_info = {
                    'name': stmt.get('name'),
                    'origName': stmt.get('origName'),
                    'varType': stmt.get('varType'),
                    'dtypeName': stmt.get('dtypeName'),
                    'isParam': stmt.get('isParam', False),
                    'isGParam': stmt.get('isGParam', False),
                    'direction': stmt.get('direction'),
                    'loc': stmt.get('loc')
                }
                
                # Categorize as parameter or logic
                # Parameters have isParam=True or isGParam=True
                if stmt.get('isParam', False) or stmt.get('isGParam', False):
                    interfaces[interface_name]['parameters'].append(var_info)
                else:
                    interfaces[interface_name]['variables'].append(var_info)
    
    return interfaces


def parse_interface_instances(json_file: str) -> Dict[str, List[Tuple[str, str]]]:
    """
    Parse a Verilator JSON file and extract all interface instances and their locations.
    
    Args:
        json_file: Path to the Verilator JSON file (e.g., top.tree.json)
        
    Returns:
        Dictionary mapping module names to lists of (instance_name, interface_type) tuples
        representing interface instantiations within each module.
    """
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    interface_instances: Dict[str, List[Tuple[str, str]]] = {}
    modules = data.get('modulesp', [])
    
    # Build mapping from module address to module name and type
    module_addr_to_info: Dict[str, Tuple[str, str]] = {}
    for module in modules:
        if module.get('type') in ['MODULE', 'IFACE']:
            addr = module.get('addr')
            name = module.get('name')
            module_type = module.get('type')
            if addr and name:
                module_addr_to_info[addr] = (name, module_type)
    
    # Extract interface instances from modules
    # Interfaces are instantiated as CELL entries that point to IFACE type modules
    for module in modules:
        if module.get('type') != 'MODULE':
            continue
        
        module_name = module.get('name')
        if not module_name:
            continue
        
        interface_instances[module_name] = []
        stmts = module.get('stmtsp', [])
        
        for stmt in stmts:
            if stmt.get('type') == 'CELL':
                instance_name = stmt.get('name')
                modp = stmt.get('modp')
                
                if instance_name and modp and modp in module_addr_to_info:
                    instantiated_name, instantiated_type = module_addr_to_info[modp]
                    if instantiated_type == 'IFACE':
                        interface_instances[module_name].append((instance_name, instantiated_name))
    
    return interface_instances


def parse_typetable(json_file: str) -> Dict[str, Dict]:
    """
    Parse the typetable from a Verilator JSON file and extract type information.
    
    Args:
        json_file: Path to the Verilator JSON file (e.g., top.tree.json)
        
    Returns:
        Dictionary mapping type addresses (as strings) to type information:
        {
            '0x...': {
                'type': 'BASICDTYPE' | 'IFACEREFDTYPE' | etc.,
                'name': 'logic' | 'int' | etc.,
                'range': '31:0' | None,
                'width': 32 | None,  # Calculated from range if available
                ...
            }
        }
    """
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    type_map = {}
    # TYPETABLE is in miscsp, not modulesp
    miscsp = data.get('miscsp', [])
    
    # Find the TYPETABLE entry
    for item in miscsp:
        if item.get('type') == 'TYPETABLE':
            typesp = item.get('typesp', [])
            for type_entry in typesp:
                addr = type_entry.get('addr')
                if addr:
                    type_info = {
                        'type': type_entry.get('type'),
                        'name': type_entry.get('name', ''),
                        'keyword': type_entry.get('keyword', ''),
                        'range': type_entry.get('range'),
                        'width': None
                    }
                    
                    # Calculate width from range if available
                    range_str = type_entry.get('range')
                    if range_str:
                        try:
                            # Parse range like "31:0" or "511:0"
                            parts = range_str.split(':')
                            if len(parts) == 2:
                                msb = int(parts[0])
                                lsb = int(parts[1])
                                type_info['width'] = msb - lsb + 1
                        except (ValueError, IndexError):
                            pass
                    
                    type_map[addr] = type_info
    
    return type_map


def get_module_signals(json_file: str, module_names: List[str]) -> Dict[str, Dict[str, Dict]]:
    """
    Extract signal information (width and direction) from module declarations by looking up types in typetable.
    
    Args:
        json_file: Path to the Verilator JSON file
        module_names: List of module names to extract signals from (e.g., ['xpm_nmu_mm', 'xpm_nsu_mm'])
        
    Returns:
        Dictionary mapping module names to signal information dictionaries:
        {
            'xpm_nmu_mm': {
                's_axi_awaddr': {
                    'width': 32,
                    'direction': 'INPUT'
                },
                's_axi_wdata': {
                    'width': 512,
                    'direction': 'INPUT'
                },
                ...
            }
        }
        Direction can be 'INPUT', 'OUTPUT', 'INOUT', or 'NONE'.
    """
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    type_map = parse_typetable(json_file)
    module_signals: Dict[str, Dict[str, Dict]] = {}
    
    modules = data.get('modulesp', [])
    for module in modules:
        if module.get('type') != 'MODULE':
            continue
        
        module_name = module.get('name')
        if module_name not in module_names:
            continue
        
        signals: Dict[str, Dict] = {}
        stmts = module.get('stmtsp', [])
        
        for stmt in stmts:
            if stmt.get('type') == 'VAR':
                # Only include ports (not internal signals, parameters, etc.)
                var_type = stmt.get('varType', '')
                if var_type != 'PORT':
                    continue
                
                signal_name = stmt.get('name')
                dtypep = stmt.get('dtypep')
                direction = stmt.get('direction', 'NONE')
                
                # Try to get width from typetable
                width = None
                if dtypep and dtypep in type_map:
                    type_info = type_map[dtypep]
                    width = type_info.get('width')
                
                # If width is still None, try to infer from dtypeName (e.g., "logic" = 1 bit)
                if width is None:
                    dtype_name = stmt.get('dtypeName', '')
                    if dtype_name in ['logic', 'bit', 'reg', 'wire']:
                        width = 1
                
                # Include the signal even if width is None (will be displayed without width)
                signals[signal_name] = {
                    'width': width,
                    'direction': direction
                }
        
        if signals:
            module_signals[module_name] = signals
    
    return module_signals


def get_interface_variables(json_file: str) -> Dict[str, Dict]:
    """
    Parse a Verilator JSON file and return interface definitions with their variables
    categorized into parameters and logics, including bitwidth and direction information from module declarations.
    
    The bitwidths and port directions are extracted from the actual module declarations (xpm_nmu_mm, xpm_nsu_mm, etc.)
    since interfaces are parameterized and don't have resolved widths.
    
    Args:
        json_file: Path to the Verilator JSON file (e.g., top.tree.json)
        
    Returns:
        Dictionary mapping interface names to their definitions:
        {
            'interface_name': {
                'name': 'interface_name',
                'parameters': [list of parameter variable info dicts],
                'logics': [list of logic variable info dicts with 'width' and 'direction' fields]
            }
        }
    """
    interfaces = parse_interface_definitions(json_file)
    
    # Get signal information from module declarations
    # These modules declare the actual signals with resolved widths
    module_names = ['xpm_nmu_mm', 'xpm_nsu_mm', 'xpm_nmu_strm', 'xpm_nsu_strm']
    module_signals = get_module_signals(json_file, module_names)
    
    # Map module signal information to interface signals
    # For AXIMM modules, use xpm_nmu_mm or xpm_nsu_mm (they should have same widths)
    # For AXIS modules, use xpm_nmu_strm or xpm_nsu_strm
    aximm_signals = module_signals.get('xpm_nmu_mm', {})
    if not aximm_signals:
        aximm_signals = module_signals.get('xpm_nsu_mm', {})
    
    axis_signals = module_signals.get('xpm_nmu_strm', {})
    if not axis_signals:
        axis_signals = module_signals.get('xpm_nsu_strm', {})
    
    # Reformat to use 'logics' instead of 'variables' for clarity
    # and add bitwidth information from module declarations
    result = {}
    for ifc_name, ifc_data in interfaces.items():
        # Determine which signal mapping to use based on interface name
        if 'axi' in ifc_name.lower() and 'axis' not in ifc_name.lower():
            signal_info_map = aximm_signals
        elif 'axis' in ifc_name.lower():
            signal_info_map = axis_signals
        else:
            signal_info_map = {}
        
        # Add width and direction information to logic variables
        logics_with_width = []
        for var in ifc_data['variables']:
            var_info = var.copy()
            signal_name = var.get('name')
            signal_info = signal_info_map.get(signal_name, {})
            var_info['width'] = signal_info.get('width') if isinstance(signal_info, dict) else None
            var_info['direction'] = signal_info.get('direction') if isinstance(signal_info, dict) else None
            var_info['range'] = None  # We don't store range, just width
            logics_with_width.append(var_info)
        
        result[ifc_name] = {
            'name': ifc_data['name'],
            'parameters': ifc_data['parameters'],
            'logics': logics_with_width
        }
    
    return result


def parse_args():
    """
    Parse command-line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Parse Verilator JSON file and print module hierarchy",
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
    
    return parser.parse_args()


def main():
    """
    Main entry point - parse command-line arguments and print module hierarchy.
    """
    args = parse_args()
    json_file = args.json_file
    
    # Check if file exists
    if not os.path.exists(json_file):
        print(f"Error: JSON file not found: {json_file}", file=sys.stderr)
        return 1
    
    try:
        print_module_hierarchy(json_file)
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
