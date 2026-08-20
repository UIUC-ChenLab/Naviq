# Historical Validation Engineering Records

This directory preserves exploratory Vivado/XSim and multi-source AXI-MM
validation material moved out of the public validation entry point during the
release cleanup. The records may be useful for future model work, but they are
not maintained instructions, release claims, or required public workflows.

| Record | Historical purpose |
| --- | --- |
| `incast_validation_record.md` | Dated validation state, diagnostic rules, and follow-up investigations. |
| `server_wave_extraction_record.md` | Dated procedure for automated Vivado/XSim waveform CSV extraction. |
| `incast_validation_findings.md` | Detailed observations, hypotheses, and model-change history. |

Use `noc_testing/experiments/validation/README.md` for the maintained
validation interface. Before relying on any archived command, output path, or
accuracy result, confirm that its inputs, tool version, and implementation
still apply to the current tree.
