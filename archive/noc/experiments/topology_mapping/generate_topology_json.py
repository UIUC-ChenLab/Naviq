#!/usr/bin/env python3
"""
Script to generate a topology JSON file with components and connections.

Parses a text file with connection data in the format:
    Component1 Port1 Channel <number> Component2 Port2
    OR
    Component1 Port1 Channel <number> Port2 Component2

The script identifies components by matching against known component names
from components_list.json.

Usage:
    python generate_topology_json.py connections_list.txt -o topology.json
"""

import json
import re
import argparse
from pathlib import Path


def load_components(components_file: str) -> dict:
    """Load components from JSON file and return as a dict keyed by name."""
    with open(components_file, 'r') as f:
        data = json.load(f)
    
    # Build a set of unique component names for quick lookup
    component_names = set()
    for comp in data['Components']:
        component_names.add(comp['Name'])
    
    return data, component_names


def is_out_port(port: str, node: str) -> bool:
    """Determine if a port is an output port (data leaves the node)."""
    if not port:
        return False
    port_lower = port.lower()
    node_lower = node.lower()
    
    if 'out' in port_lower: return True
    if 'in' in port_lower: return False
    
    # Implicit output directions
    if 'nmu' in node_lower and 'req' in port_lower: return True
    if 'nsu' in node_lower and 'resp' in port_lower: return True
    if 'ddr' in node_lower and 'resp' in port_lower: return True
    if 'hbm' in node_lower and 'resp' in port_lower: return True
    
    return False


def is_in_port(port: str, node: str) -> bool:
    """Determine if a port is an input port (data enters the node)."""
    if not port:
        return False
    port_lower = port.lower()
    node_lower = node.lower()
    
    if 'in' in port_lower: return True
    if 'out' in port_lower: return False
    
    # Implicit input directions
    if 'nmu' in node_lower and 'resp' in port_lower: return True
    if 'nsu' in node_lower and 'req' in port_lower: return True
    if 'ddr' in node_lower and 'req' in port_lower: return True
    if 'hbm' in node_lower and 'req' in port_lower: return True
    
    return False


def parse_connection_line(line: str, known_components: set) -> dict | None:
    """
    Parse a single connection line.
    
    Expected format variations:
        Component1 Port1 Channel <num> Component2 Port2
        Component1 Port1 Channel <num> Port2 Component2
    
    Returns a connection dict or None if parsing fails.
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    
    # Remove trailing period if present
    line = line.rstrip('.')
    
    # Find the channel number - this is our anchor point
    channel_match = re.search(r'\bChannel\s+(\d+)\b', line, re.IGNORECASE)
    if not channel_match:
        print(f"Warning: Could not find 'Channel <number>' in line: {line}")
        return None
    
    channel_num = int(channel_match.group(1))
    
    # Split the line into before and after the channel marker
    before_channel = line[:channel_match.start()].strip()
    after_channel = line[channel_match.end():].strip()
    
    # Parse the "before channel" part - should be: Component1 Port1
    tokens_before = before_channel.split()
    if len(tokens_before) < 2:
        print(f"Warning: Could not parse source component/port in: {line}")
        return None
    
    # Try to find a known component in the before tokens
    source_component = None
    source_port = None
    for i, token in enumerate(tokens_before):
        if token in known_components:
            source_component = token
            # Port is everything else (all tokens except the component)
            remaining = tokens_before[:i] + tokens_before[i+1:]
            source_port = ' '.join(remaining) if remaining else None
            break
    
    # If no known component found, assume first token is component
    if source_component is None:
        source_component = tokens_before[0]
        source_port = ' '.join(tokens_before[1:]) if len(tokens_before) > 1 else None
    
    # Parse the "after channel" part - could be: Component2 Port2 OR Port2 Component2
    tokens_after = after_channel.split()
    if len(tokens_after) < 2:
        print(f"Warning: Could not parse target component/port in: {line}")
        return None
    
    # Try to find a known component in the after tokens
    target_component = None
    target_port = None
    for i, token in enumerate(tokens_after):
        if token in known_components:
            target_component = token
            # Port is everything else (all tokens except the component)
            remaining = tokens_after[:i] + tokens_after[i+1:]
            target_port = ' '.join(remaining) if remaining else None
            break
    
    # If no known component found, assume last token is component (common pattern)
    if target_component is None:
        target_component = tokens_after[-1]
        target_port = ' '.join(tokens_after[:-1]) if len(tokens_after) > 1 else None
    
    if not source_component or not target_component:
        print(f"Warning: Could not identify both components in: {line}")
        return None
    
    source_port_str = source_port or ""
    target_port_str = target_port or ""

    # Enforce data flow direction: OUT -> IN
    src_is_in = is_in_port(source_port_str, source_component)
    tgt_is_out = is_out_port(target_port_str, target_component)
    
    if tgt_is_out and (src_is_in or not is_out_port(source_port_str, source_component)):
        # The line is listed as IN -> OUT. Swap to make it OUT -> IN.
        source_component, target_component = target_component, source_component
        source_port_str, target_port_str = target_port_str, source_port_str

    return {
        "Source": source_component,
        "SourcePort": source_port_str,
        "Channel": channel_num,
        "Target": target_component,
        "TargetPort": target_port_str
    }


def parse_connections_file(connections_file: str, known_components: set) -> list:
    """Parse the connections text file and return a list of connection dicts."""
    connections = []
    
    with open(connections_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            conn = parse_connection_line(line, known_components)
            if conn:
                connections.append(conn)
    
    return connections


def generate_connections_json(components_file: str, connections_file: str, output_file: str):
    """Generate the connections JSON file."""
    
    # Load components for validation
    components_data, known_components = load_components(components_file)
    print(f"Loaded {len(known_components)} unique component names from {components_file}")
    
    # Parse connections
    connections = parse_connections_file(connections_file, known_components)
    print(f"Parsed {len(connections)} connections from {connections_file}")
    
    # Warn about unknown components in connections
    for conn in connections:
        if conn['Source'] not in known_components:
            print(f"Warning: Source component '{conn['Source']}' not in components list")
        if conn['Target'] not in known_components:
            print(f"Warning: Target component '{conn['Target']}' not in components list")
    
    # Build output structure - just connections
    output = {
        "Connections": connections
    }
    
    # Write output
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Generated connections JSON with {len(connections)} connections")
    print(f"Output written to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate connections JSON from a text file of connection data'
    )
    parser.add_argument(
        'connections_file',
        help='Path to the connections text file'
    )
    parser.add_argument(
        '-c', '--components',
        default='components_list.json',
        help='Path to the components JSON file for validation (default: components_list.json)'
    )
    parser.add_argument(
        '-o', '--output',
        default='connections_list.json',
        help='Output JSON file path (default: connections_list.json)'
    )
    
    args = parser.parse_args()
    
    # Resolve paths relative to script directory if not absolute
    script_dir = Path(__file__).parent
    
    components_path = Path(args.components)
    if not components_path.is_absolute() and not components_path.exists():
        components_path = script_dir / components_path
    
    connections_path = Path(args.connections_file)
    if not connections_path.is_absolute() and not connections_path.exists():
        connections_path = script_dir / connections_path
    
    output_path = Path(args.output)
    if not output_path.is_absolute() and not output_path.exists():
        output_path = script_dir / output_path
    
    generate_connections_json(str(components_path), str(connections_path), str(output_path))


if __name__ == '__main__':
    main()
