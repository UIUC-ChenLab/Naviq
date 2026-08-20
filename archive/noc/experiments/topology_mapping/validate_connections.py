#!/usr/bin/env python3
"""
Validate connections file for duplicates and show progress.

Checks for:
1. Duplicate endpoint+port combinations
2. Duplicate channel numbers
3. Progress: percentage of components from components_list.json that are connected

Usage:
    python validate_connections.py connections_list.txt
"""

import os
import json
import re
import argparse
from pathlib import Path
from collections import defaultdict


def load_components(components_file: str) -> set:
    """Load component names from JSON file."""
    with open(components_file, 'r') as f:
        data = json.load(f)
    
    component_names = set()
    for comp in data.get('Components', []):
        component_names.add(comp['Name'])
    
    return component_names


def parse_connection_line(line: str, known_components: set) -> dict | None:
    """Parse a single connection line and extract components, ports, and channel.
    
    Uses known_components to properly identify which token is the component
    vs the port, regardless of order.
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    
    line = line.rstrip('.')
    
    # Find the channel number
    channel_match = re.search(r'\bChannel\s+(\d+)\b', line, re.IGNORECASE)
    if not channel_match:
        return None
    
    channel_num = int(channel_match.group(1))
    before_channel = line[:channel_match.start()].strip()
    after_channel = line[channel_match.end():].strip()
    
    # Parse tokens
    tokens_before = before_channel.split()
    tokens_after = after_channel.split()
    
    if len(tokens_before) < 2 or len(tokens_after) < 2:
        return None
    
    # For "before channel" - find which token is the known component
    source_component = None
    source_port = None
    for i, token in enumerate(tokens_before):
        if token in known_components:
            source_component = token
            # Port is everything else
            remaining = tokens_before[:i] + tokens_before[i+1:]
            source_port = ' '.join(remaining)
            break
    
    # If no known component found, assume first token is component
    if source_component is None:
        source_component = tokens_before[0]
        source_port = ' '.join(tokens_before[1:])
    
    # For "after channel" - find which token is the known component
    target_component = None
    target_port = None
    for i, token in enumerate(tokens_after):
        if token in known_components:
            target_component = token
            # Port is everything else
            remaining = tokens_after[:i] + tokens_after[i+1:]
            target_port = ' '.join(remaining)
            break
    
    # If no known component found, assume last token is component (common pattern)
    if target_component is None:
        target_component = tokens_after[-1]
        target_port = ' '.join(tokens_after[:-1])
    
    return {
        'source': source_component,
        'source_port': source_port,
        'target': target_component,
        'target_port': target_port,
        'channel': channel_num,
        'original_line': line
    }


def validate_connections(connections_file: str, components_file: str = None, all_components_file: str = None):
    """Validate the connections file and report issues."""
    
    known_components = set()
    
    # Load known components from JSON
    if components_file and os.path.exists(components_file):
        json_comps = load_components(components_file)
        known_components.update(json_comps)
        print(f"Loaded {len(json_comps)} unique components from {components_file}\n")
    elif components_file:
        print(f"Warning: Components JSON {components_file} not found.\n")
    
    expected_endpoints = set()
    expected_channels = set()
    if all_components_file and os.path.exists(all_components_file):
        with open(all_components_file, 'r') as f:
            lines = f.read().splitlines()
            if len(lines) >= 1:
                expected_endpoints = set(lines[0].split())
            if len(lines) >= 2:
                expected_channels = {int(x) for x in lines[1].split() if x.lower() != 'channel'}
        print(f"Loaded {len(expected_endpoints)} expected endpoints and {len(expected_channels)} expected channels from {all_components_file}\n")
        known_components.update(expected_endpoints)
    elif all_components_file:
        print(f"Warning: {all_components_file} not found. Skipping completeness checks.\n")
    
    if not known_components:
        print("Warning: No components loaded to help parse connection lines. Parsing may be less accurate.\n")
    
    # Track for duplicate detection
    endpoint_port_combos = defaultdict(list)  # (component, port) -> [line_numbers]
    channel_numbers = defaultdict(list)  # channel -> [line_numbers]
    connected_components = set()
    
    # Parse all connections
    connections = []
    with open(connections_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            conn = parse_connection_line(line, known_components)
            if conn:
                conn['line_num'] = line_num
                connections.append(conn)
                
                # Track endpoint+port combos
                source_key = (conn['source'], conn['source_port'])
                target_key = (conn['target'], conn['target_port'])
                endpoint_port_combos[source_key].append(line_num)
                endpoint_port_combos[target_key].append(line_num)
                
                # Track channel numbers
                channel_numbers[conn['channel']].append(line_num)
                
                # Track connected components
                connected_components.add(conn['source'])
                connected_components.add(conn['target'])
    
    print(f"Parsed {len(connections)} connections from {connections_file}\n")
    
    # Check for duplicate endpoint+port combinations
    print("=" * 60)
    print("DUPLICATE ENDPOINT+PORT COMBINATIONS")
    print("=" * 60)
    dup_endpoints = 0
    for (component, port), lines in sorted(endpoint_port_combos.items()):
        if len(lines) > 1:
            dup_endpoints += 1
            print(f"  {component} {port}")
            print(f"    Found on lines: {lines}")
    
    if dup_endpoints == 0:
        print("  ✓ No duplicate endpoint+port combinations found!")
    else:
        print(f"\n  ⚠ Found {dup_endpoints} duplicate endpoint+port combinations")
    
    # Check for duplicate channel numbers
    print("\n" + "=" * 60)
    print("DUPLICATE CHANNEL NUMBERS")
    print("=" * 60)
    dup_channels = 0
    for channel, lines in sorted(channel_numbers.items()):
        if len(lines) > 1:
            dup_channels += 1
            print(f"  Channel {channel}")
            print(f"    Found on lines: {lines}")
    
    if dup_channels == 0:
        print("  ✓ No duplicate channel numbers found!")
    else:
        print(f"\n  ⚠ Found {dup_channels} duplicate channel numbers")
    
    # Check for unknown components
    print("\n" + "=" * 60)
    print("UNKNOWN COMPONENTS (not in provided lists)")
    print("=" * 60)
    unknown = connected_components - known_components
    if unknown:
        for comp in sorted(unknown):
            print(f"  ⚠ {comp}")
        print(f"\n  Found {len(unknown)} unknown components")
    else:
        print("  ✓ All components match the provided lists!")
    
    # Check for missing expected endpoints
    missing_endpoints = set()
    if expected_endpoints:
        print("\n" + "=" * 60)
        print("MISSING EXPECTED ENDPOINTS")
        print("=" * 60)
        missing_endpoints = expected_endpoints - connected_components
        if missing_endpoints:
            for comp in sorted(missing_endpoints):
                print(f"  ⚠ {comp}")
            print(f"\n  Found {len(missing_endpoints)} missing expected endpoints")
        else:
            print("  ✓ All expected endpoints are present!")

    # Check for missing expected channels
    missing_channels = set()
    if expected_channels:
        print("\n" + "=" * 60)
        print("MISSING EXPECTED CHANNELS")
        print("=" * 60)
        missing_channels = expected_channels - set(channel_numbers.keys())
        if missing_channels:
            for ch in sorted(missing_channels):
                print(f"  ⚠ Channel {ch}")
            print(f"\n  Found {len(missing_channels)} missing expected channels")
        else:
            print("  ✓ All expected channels are present!")
    
    # Progress report
    if known_components:
        print("\n" + "=" * 60)
        print("PROGRESS REPORT")
        print("=" * 60)
        
        # Only count known components for progress
        known_connected = connected_components & known_components
        progress_pct = (len(known_connected) / len(known_components)) * 100
        
        print(f"  Total components in list:  {len(known_components)}")
        print(f"  Components connected:      {len(known_connected)}")
        print(f"  Progress:                  {progress_pct:.1f}%")
        
        # Visual progress bar
        bar_width = 40
        filled = int(bar_width * progress_pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        print(f"\n  [{bar}] {progress_pct:.1f}%")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    issues = dup_endpoints + dup_channels + len(unknown) + len(missing_endpoints) + len(missing_channels)
    if issues == 0:
        print("  ✓ No issues found! File looks good.")
    else:
        print(f"  ⚠ Found {issues} total issue(s) to review")
    
    return issues == 0


def main():
    parser = argparse.ArgumentParser(
        description='Validate connections file for duplicates and show progress'
    )
    parser.add_argument(
        'connections_file',
        help='Path to the connections text file'
    )
    parser.add_argument(
        '-c', '--components',
        default=None,
        help='Path to the components JSON file (optional)'
    )
    parser.add_argument(
        '-a', '--all-components',
        default='all_noc_components.txt',
        help='Path to the all noc components text file (default: all_noc_components.txt)'
    )
    
    args = parser.parse_args()
    
    script_dir = Path(__file__).parent
    
    components_path = None
    if args.components:
        components_path = Path(args.components)
        if not components_path.is_absolute() and not components_path.exists():
            components_path = script_dir / components_path
    
    all_components_path = None
    if args.all_components:
        all_components_path = Path(args.all_components)
        if not all_components_path.is_absolute() and not all_components_path.exists():
            all_components_path = script_dir / all_components_path
    
    connections_path = Path(args.connections_file)
    if not connections_path.is_absolute() and not connections_path.exists():
        connections_path = script_dir / connections_path
    
    validate_connections(
        str(connections_path),
        str(components_path) if components_path else None,
        str(all_components_path) if all_components_path else None
    )


if __name__ == '__main__':
    main()
