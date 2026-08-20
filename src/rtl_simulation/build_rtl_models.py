#!/usr/bin/env python3
"""
Build RTL models by verilating SystemVerilog designs.

This script should be run from the rtl_simulation directory:
    cd src/rtl_simulation
    python3 build_rtl_models.py
"""

import os
import sys
import glob
import json
import shutil
import subprocess
import argparse

from rtl_manifest import ManifestError, build_gem5_plan, build_spec, load_manifest


def load_external_designs(script_dir):
    manifest_path = os.path.join(script_dir, "external_designs.json")
    if not os.path.exists(manifest_path):
        return []

    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    external_designs = []
    for entry in manifest:
        name = entry["name"]
        top_module = entry.get("top_module", name)
        sources = [
            os.path.normpath(os.path.join(script_dir, src))
            for src in entry.get("sources", [])
        ]
        for pattern in entry.get("source_globs", []):
            sources.extend(
                sorted(glob.glob(os.path.normpath(os.path.join(script_dir, pattern))))
            )
        include_dirs = [
            os.path.normpath(os.path.join(script_dir, inc))
            for inc in entry.get("include_dirs", [])
        ]
        base_extra_args = list(entry.get("extra_args", []))
        variants = entry.get("variants", [{"name": name}])
        for variant in variants:
            variant_name = variant["name"]
            external_designs.append(
                {
                    "name": variant_name,
                    "top_module": variant.get("top_module", top_module),
                    "sources": sources,
                    "include_dirs": include_dirs,
                    "extra_args": base_extra_args + list(variant.get("extra_args", [])),
                }
            )

    return external_designs

def main():
    parser = argparse.ArgumentParser(description='Build RTL models by verilating SystemVerilog designs')
    parser.add_argument('--build-dir', type=str, default=None,
                        help='Build directory for output (default: ./build)')
    parser.add_argument('--design', action='append', default=[],
                        help='Only build the named design(s); may be passed multiple times')
    parser.add_argument('--manifest', action='append', default=[],
                        help='RTL integration manifest; may be passed multiple times')
    args = parser.parse_args()
    
    # Get the directory where this script lives
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Set up paths
    hw_dir = os.path.join(script_dir, 'hw')
    designs_dir = os.path.join(hw_dir, 'designs')
    include_dir = os.path.join(hw_dir, 'include')
    build_dir = args.build_dir if args.build_dir else os.path.join(script_dir, 'build')
    
    # Find all .sv files in the include directory
    include_files = glob.glob(os.path.join(include_dir, '*.sv'))
    
    # Find all in-tree design directories
    design_dirs = []
    if os.path.exists(designs_dir):
        for item in os.listdir(designs_dir):
            design_path = os.path.join(designs_dir, item)
            if os.path.isdir(design_path):
                design_dirs.append(item)

    default_design_specs = []
    for design_name in design_dirs:
        design_dir = os.path.join(designs_dir, design_name)
        design_sv_files = glob.glob(os.path.join(design_dir, "*.sv"))
        if not design_sv_files:
            print(f"  Warning: No .sv files found in {design_dir}, skipping")
            continue

        default_design_specs.append(
            {
                "name": design_name,
                "top_module": design_name,
                "sources": design_sv_files + include_files,
                "include_dirs": [design_dir, include_dir],
                "extra_args": [],
            }
        )

    default_design_specs.extend(load_external_designs(script_dir))

    manifest_specs = []
    for manifest_path in args.manifest:
        try:
            manifest_specs.append(build_spec(load_manifest(manifest_path)))
        except (ManifestError, OSError, json.JSONDecodeError) as error:
            parser.error("invalid manifest '{}': {}".format(manifest_path, error))

    # A manifest invocation is intentionally isolated.  It should not also
    # build every local prototype or externally listed design.
    design_specs = manifest_specs if manifest_specs else default_design_specs

    if args.design:
        requested = set(args.design)
        available = {spec["name"] for spec in design_specs}
        missing = sorted(requested - available)
        if missing:
            print(f"Unknown design(s): {', '.join(missing)}")
            print(f"Available design(s): {', '.join(sorted(available))}")
            return 1
        design_specs = [spec for spec in design_specs if spec["name"] in requested]

    if not design_specs:
        print("No design directories found in hw/designs/")
        return 0

    print(
        "RTL Simulation: Found {} design(s): {}".format(
            len(design_specs),
            ", ".join(spec["name"] for spec in design_specs),
        )
    )

    # Process each design
    for spec in design_specs:
        design_name = spec["name"]
        print(f"\nVerilating {design_name}...")

        # Output directory for verilated files
        output_dir = os.path.join(build_dir, design_name)

        # Clean the output directory before building
        if os.path.exists(output_dir):
            print(f"  Cleaning output directory: {output_dir}")
            shutil.rmtree(output_dir)

        # Create fresh output directory
        os.makedirs(output_dir, exist_ok=True)

        # Build common verilator arguments
        module_name = spec["name"]
        top_module = spec["top_module"]
        common_args = ['-Wno-fatal']
        for inc_dir in spec["include_dirs"]:
            common_args.append('-I' + inc_dir)
        common_args.extend(spec["extra_args"])
        common_args.extend(['--top-module', top_module])
        common_args.extend(['--prefix', module_name])

        # Add all source files
        common_args.extend(spec["sources"])

        # First run: Generate C++ code (--cc mode)
        print(f"  Running verilator (C++ generation)...")
        cmd_parts_cc = ['verilator', '--cc'] + common_args
        cmd_parts_cc.extend(['--Mdir', output_dir])
        
        result = subprocess.run(cmd_parts_cc, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: Verilator C++ generation failed for {design_name}:")
            print(result.stdout)
            print(result.stderr)
            return 1
        
        # Second run: Generate tree.json (--json-only mode)
        print(f"  Running verilator (JSON generation)...")
        cmd_parts_json = ['verilator', '--json-only', '--no-json-ids'] + common_args
        cmd_parts_json.extend(['--Mdir', output_dir])
        
        result = subprocess.run(cmd_parts_json, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: Verilator JSON generation failed for {design_name}:")
            print(result.stdout)
            print(result.stderr)
            return 1
        
        # Third step: Generate C++ headers using generate_noc_cpp.py
        tree_json_path = os.path.join(output_dir, f'{module_name}.tree.json')
        if not os.path.exists(tree_json_path):
            print(f"  ERROR: tree.json file not found at {tree_json_path}")
            return 1
        
        print(f"  Running generate_noc_cpp.py...")
        generate_script = os.path.join(script_dir, 'generate_noc_cpp.py')
        if not os.path.exists(generate_script):
            print(f"  ERROR: generate_noc_cpp.py not found at {generate_script}")
            return 1
        
        endpoint_map_path = os.path.join(
            output_dir, f'{module_name}_noc_endpoints.json'
        )
        cmd_generate = [
            sys.executable,
            generate_script,
            tree_json_path,
            '--prefix',
            module_name,
            '--endpoint-map-output',
            endpoint_map_path,
        ]
        result = subprocess.run(cmd_generate, cwd=output_dir, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: generate_noc_cpp.py failed for {design_name}:")
            print(result.stdout)
            print(result.stderr)
            return 1

        if "manifest" in spec:
            try:
                with open(endpoint_map_path, encoding="utf-8") as source:
                    endpoint_map = json.load(source)
                gem5_plan = build_gem5_plan(spec["manifest"], endpoint_map)
            except (ManifestError, OSError, json.JSONDecodeError) as error:
                print(f"  ERROR: RTL/gem5 endpoint validation failed: {error}")
                return 1
            gem5_plan_path = os.path.join(
                output_dir, f'{module_name}_gem5_plan.json'
            )
            with open(gem5_plan_path, 'w', encoding='utf-8') as output:
                json.dump(gem5_plan, output, indent=2)
                output.write('\n')
            print(f"  Generated gem5 connection plan: {gem5_plan_path}")
        
        # Create marker file to indicate successful verilation
        marker_path = os.path.join(output_dir, 'verilated.stamp')
        with open(marker_path, 'w') as f:
            f.write(f'Verilated {design_name}\n')
        
        print(f"  ✓ Successfully verilated {design_name}")
    
    print(f"\n✓ All designs verilated successfully")
    print(f"Output directory: {build_dir}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
