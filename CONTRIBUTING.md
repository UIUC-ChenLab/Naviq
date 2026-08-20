# Contributing to Naviq

Thank you for contributing to Naviq. Naviq is derived from gem5, but changes to
this repository should be proposed through the Naviq GitHub repository rather
than through gem5's issue tracker or review process.

## Before starting

- Search the Naviq issues and pull requests for related work.
- Open an issue before beginning a large feature or behavior change.
- Base changes on the current `main` branch and keep each pull request focused.
- Do not include proprietary designs, credentials, generated build products,
  or data that cannot be redistributed publicly.

## Development setup

Create an isolated Python environment and install the project requirements:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install pre-commit
pre-commit install
```

Build the portable NoC configuration:

```bash
scons --no-compress-debug build/NULL/gem5.opt -j$(nproc)
```

## Tests

Run the checks relevant to your change. The baseline NoC checks are:

```bash
cd tests
./main.py run --skip-build --length=quick --isa=NULL --variant=opt gem5/noc
cd ..
src/noc/testing/run_noc_gtests.sh
python3 noc_testing/experiments/run_experiment.py --dry-run-all
```

Changes involving Vivado or other licensed tools must document the required
tool version and should retain a portable validation path where possible.

## Style and commits

- Follow the style of nearby gem5 code.
- Use four spaces, avoid tabs and trailing whitespace, and keep lines concise.
- Run `pre-commit run --all-files` before submitting a pull request.
- Write an imperative, scoped commit subject, for example
  `noc: Fix AXIS packet completion accounting`.
- Explain user-visible behavior, test coverage, and known limitations in the
  pull request description.

## Review

All changes are reviewed through pull requests. Tests must pass and review
comments must be resolved before merge. Maintainers may request smaller or
more focused changes when a pull request mixes unrelated work.

Project owner and maintainer: **Professor Deming Chen**, University of
Illinois Urbana-Champaign.
