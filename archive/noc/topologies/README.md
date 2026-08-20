# Archived topology fixtures

This directory preserves historical `.ncr` and `.nts` topology pairs.  It is
not an entry point for new tests or experiment campaigns.

Use maintained fixtures under `src/noc/testing/fixtures/topologies/` for new
deterministic tests, and use the paths declared by a manifest under
`noc_testing/experiments/` for maintained evaluations.

The former SmartNIC rate-limiter dependency was migrated to
`src/noc/testing/fixtures/topologies/smartnic/axis_module_smoke`. No maintained
scenario should read an archived topology directly.

Before retiring any file in this directory, first verify its references with:

```sh
git grep -n -E 'archive/noc/topologies|topology/topologies/old'
```

Historical fixtures are retained in Git history and the repository's archival
branch record; they must not be copied into new test output directories.
