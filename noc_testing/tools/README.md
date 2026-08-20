# NoC experiment tools

Reusable tools that support maintained experiments live here. They are not
campaigns themselves: campaigns are declared under `noc_testing/experiments/`
and launched through the manifest runner.

- `topology/` generates and validates topology descriptions from checked-in
  connection and placement inputs. For example:

  ```sh
  python3 noc_testing/tools/topology/generate_ncr.py --help
  ```

- `visualization/` contains the interactive NPS queue heatmap tool. Invoke it
  with a caller-supplied trace, floorplan image, and coordinates JSON. The
  historical sample assets live in
  `archive/noc/experiments/visualization_samples/`; they are not regression
  baselines.

Historical topology-mapping and plotting utilities are preserved under
`archive/noc/` and are not maintained public tools.
