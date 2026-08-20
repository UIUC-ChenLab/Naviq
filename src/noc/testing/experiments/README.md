# NoC Experiments

This directory contains named experiment campaigns that sit above the reusable
smoke scenarios in sibling directories such as `hbm_smartnic/` and `smartnic/`.

Use this area for runs that need a stable label, comparison driver, result
criteria, or report-oriented organization. Keep generic helpers and shared
traffic setup in the existing family directories when other tests depend on
them.

Existing direct-run scripts may remain in their original directories as
compatibility entry points while the canonical experiment driver lives here.
