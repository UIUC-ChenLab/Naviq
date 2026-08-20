#!/usr/bin/env python3
"""
get_vivado_topology.py

Simple utility to copy .nts and .ncr files from a local Vivado project
to the same directory as this script for easy access.

Usage:
    python get_vivado_topology.py                 # Uses defaults
    python get_vivado_topology.py --list          # List available files
    python get_vivado_topology.py --bd my_design  # Custom BD name
"""

import os
import shutil
import argparse
from pathlib import Path

# ======================== CONFIGURATION - EDIT THESE ========================
# Path to the Vivado project directory (relative to this script's location)
VIVADO_PROJ_DIR = "vivado_proj/noc_tg_sweep"
PROJECT_NAME = "noc_tg_sweep"
BD_NAME = "noc_subsystem"  # The block design name
# =============================================================================


def get_script_dir() -> Path:
    """Get the directory where this script is located."""
    return Path(__file__).parent.resolve()


def get_nsln_dir(script_dir: Path, proj_dir: str, proj_name: str, bd_name: str) -> Path:
    """
    Get the path to the nsln directory containing .nts and .ncr files.
    
    Standard Vivado layout:
    <project_dir>/<project_name>.gen/sources_1/bd/<bd_name>/nsln/
    """
    return script_dir / proj_dir / f"{proj_name}.gen" / "sources_1" / "bd" / bd_name / "nsln"


def list_available_files(script_dir: Path, proj_dir: str, proj_name: str, bd_name: str):
    """List available .nts and .ncr files in the Vivado project."""
    nsln_dir = get_nsln_dir(script_dir, proj_dir, proj_name, bd_name)
    
    print(f"\nSearching in: {nsln_dir}")
    
    if not nsln_dir.exists():
        print(f"  ERROR: Directory does not exist!")
        print(f"\n  Make sure you have:")
        print(f"    1. Generated the block design in Vivado")
        print(f"    2. Run 'Generate Block Design' or simulation")
        return
    
    nts_files = list(nsln_dir.glob("*.nts"))
    ncr_files = list(nsln_dir.glob("*.ncr"))
    
    print(f"\n  Found {len(nts_files)} .nts file(s):")
    for f in nts_files:
        print(f"    - {f.name}")
    
    print(f"\n  Found {len(ncr_files)} .ncr file(s):")
    for f in ncr_files:
        print(f"    - {f.name}")


def copy_topology_files(
    script_dir: Path,
    proj_dir: str,
    proj_name: str,
    bd_name: str,
    output_prefix: str = None
):
    """
    Copy .nts and .ncr files from Vivado project to this script's directory.
    
    Args:
        script_dir: Directory where this script is located
        proj_dir: Relative path to Vivado project directory
        proj_name: Vivado project name
        bd_name: Block design name
        output_prefix: Optional prefix for output files (e.g., "my_design")
    """
    nsln_dir = get_nsln_dir(script_dir, proj_dir, proj_name, bd_name)
    
    nts_src = nsln_dir / f"{bd_name}.nts"
    ncr_src = nsln_dir / f"{bd_name}.ncr"
    
    # Check if source files exist
    if not nts_src.exists():
        print(f"ERROR: NTS file not found: {nts_src}")
        return False
    if not ncr_src.exists():
        print(f"ERROR: NCR file not found: {ncr_src}")
        return False
    
    # Determine output filenames
    prefix = output_prefix if output_prefix else bd_name
    nts_dst = script_dir / f"{prefix}.nts"
    ncr_dst = script_dir / f"{prefix}.ncr"
    
    # Copy the files
    print(f"Copying NoC topology files from Vivado project...")
    print(f"  Source dir: {nsln_dir}")
    print()
    
    shutil.copy2(nts_src, nts_dst)
    print(f"  [OK] {nts_src.name} -> {nts_dst.name}")
    
    shutil.copy2(ncr_src, ncr_dst)
    print(f"  [OK] {ncr_src.name} -> {ncr_dst.name}")
    
    print()
    print(f"Files copied to: {script_dir}")
    print()
    print("You can now move these files wherever you need them:")
    print(f"  {nts_dst}")
    print(f"  {ncr_dst}")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Copy .nts and .ncr topology files from Vivado project"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available files without copying"
    )
    parser.add_argument(
        "--proj-dir",
        default=VIVADO_PROJ_DIR,
        help=f"Path to Vivado project (default: {VIVADO_PROJ_DIR})"
    )
    parser.add_argument(
        "--proj-name",
        default=PROJECT_NAME,
        help=f"Vivado project name (default: {PROJECT_NAME})"
    )
    parser.add_argument(
        "--bd",
        default=BD_NAME,
        help=f"Block design name (default: {BD_NAME})"
    )
    parser.add_argument(
        "--output-prefix", "-o",
        default=None,
        help="Prefix for output files (default: same as BD name)"
    )
    
    args = parser.parse_args()
    script_dir = get_script_dir()
    
    print(f"=== Vivado NoC Topology File Copier ===")
    print(f"Script location: {script_dir}")
    
    if args.list:
        list_available_files(script_dir, args.proj_dir, args.proj_name, args.bd)
    else:
        copy_topology_files(
            script_dir,
            args.proj_dir,
            args.proj_name,
            args.bd,
            args.output_prefix
        )


if __name__ == "__main__":
    main()
