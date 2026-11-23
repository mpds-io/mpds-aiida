# AGENTS.md

## Project

**mpds-aiida** — AiiDA workflows and utilities for the MPDS online ecosystem.
Provides cloud-based, reproducible ab-initio simulations of crystalline
materials using the MPDS data platform, AiiDA workflows, the CRYSTAL and FLEUR
simulation engines, and the yascheduler cloud scheduler.

- Homepage: https://github.com/mpds-io/mpds-aiida
- License: MIT
- Language: Python (>=3.9)
- Version: see `mpds_aiida/__init__.py` (`__version__`); currently `0.11.3`.

## Tech stack

- Python, setuptools build backend (`pyproject.toml`); `reentry` is required at
  build time.
- AiiDA workflows (`aiida-core < 2.9.0`), `aiida-phonopy`, `aiida-fleur>=2.0.0`,
  `aiida-crystal-dft` (installed from git), `aiida-reoptimize` (from git).
- `mpds_client` for MPDS API access.
- `yascheduler >= 1.6.0` for cloud scheduling of remote CRYSTAL/FLEUR jobs.
- `ase >= 3.19`, `numpy >= 1.17.5`, `phonopy == 2.19.1`, `jsonschema <= 3.2.0`.
- Pre-commit hooks: `ruff` v0.15.8 (check + format), generic hygiene hooks
  (`.pre-commit-config.yaml`).
- Testing: `pytest` with AiiDA fixtures from `conftest.py`.

## Project layout

```
mpds_aiida/                # main package
  __init__.py              # __version__
  common.py                # shared helpers
  chemical_formulae.py     # formula parsing
  inputs.py, properties.py, quantities.py, export.py, spacegroups.py
  calc_templates/          # YAML calculation templates (engine settings)
    benchmark_pcrystal.yml # PBE0 + SHRINK 8 16 + TOLDEE 9 + MPDSBSL_NEUTRAL_6TH
    benchmark_fleur.yml    # PBE-GGA + kmax=2.5 + 2x2x2 k-mesh + FLAPW MT radii
    nonmetallic.yml, metallic.yml, flapw_default.yml, minimal.yml,
    nonmetallic_test.yml
  workflows/               # AiiDA workchains
    __init__.py            # exports MPDSCrystalSeebeckWorkChain
    crystal_mpds.py        # MPDSStructureWorkchain  (entry point: crystal.mpds)
    crystal_seebeck.py     # MPDSCrystalSeebeckWorkChain (entry: crystal.mpds_seebeck)
    cif.py                 # CIFStructureWorkchain   (entry: crystal.cif)
    aiida.py               # AiidaStructureWorkchain (entry: crystal.aiida)
    fleur_mpds.py          # MPDSFleurStructureWorkChain (entry: fleur.mpds)
    fleur_phonopy.py       # PhonopyFleurWorkChain, FleurForcesWorkChain
                           #   (entries: phonopy.fleur, fleur.forces)
    fleur_seebeck.py       # FleurDOSLocalWorkChain (entry: fleur.dos_seebeck)
    crystal.py, fleur_base.py, properties.py
  benchmark/               # perovskite benchmark pipeline + CLI
    __init__.py            # package docstring linking to scripts/README_benchmark.md
    cli.py                 # `mpds-benchmark` entry point (argparse)
    pipeline.py            # run_benchmark / run_benchmark_both / validate_env
                           #   / load_template / print_comparison_table
    report.py              # BenchmarkReport dataclass + to_json/from_json
  tests/                   # pytest suite
    fixtures.py, __init__.py
    basis/, mock/, output_files/, phonopy_fleur/
    test_benchmark_report.py  # BenchmarkReport serialization unit test
    test_benchmark_cli.py      # CLI arg parsing + env-var validation unit test
    test_workflow.py
bs_library/               # Gaussian basis set library
scripts/                   # helper scripts
  aiida_submit_phase.py    # manual AiiDA workchain submission (pre-benchmark era)
  aiida_submit_ht_test.py, aiida_submit_cif.py
  ya_submit_cif.py, ya_submit_ht_test.py
  run_properties.py, run_seebeck_pipeline.py, run_template.py
  launch_pproperties.py, restart_workchains.py
  bs_unito_download.py     # download CRYSTAL basis sets from crystal.unito.it
  README_benchmark.md      # benchmark pipeline user documentation
deploy/                   # deployment configs
  aiida_setup.sh, install.sh, cloud.sh
  postgresql.conf, supervisord.conf, sysctl.conf, yascheduler.conf
openspec/                 # OpenSpec spec-driven change tracking (see below)
conftest.py               # pytest fixtures: aiida_profile, new_database, new_workdir
pyproject.toml            # build, deps, entry points
.pre-commit-config.yaml
CITATION.cff, LICENSE, README.md
```

AiiDA workflow entry points are declared under
`[project.entry-points."aiida.workflows"]` in `pyproject.toml` (8 workchains,
see the layout above for the mapping). The `mpds-benchmark` CLI is declared
under `[project.scripts]` as
`mpds-benchmark = "mpds_aiida.benchmark.cli:main"`.

## Setup

The package depends on `aiida-crystal-dft`, `aiida-reoptimize`, and `yascheduler`,
which are installed from git (see `README.md`):

```shell
pip install git+https://github.com/tilde-lab/aiida-crystal-dft
pip install git+https://github.com/mpds-io/aiida-reoptimize
pip install git+https://github.com/tilde-lab/yascheduler
pip install mpds-aiida/
```

A working AiiDA profile and a `yascheduler` daemon are expected for end-to-end
runs. SSH to `localhost` must be keyless for AiiDA's local "remote" computer.
For benchmarks, the AiiDA computer must be `yascheduler` (SSH transport,
yascheduler scheduler) with codes `Pcrystal@yascheduler` and
`fleur@yascheduler` registered, and the basis set family
`MPDSBSL_NEUTRAL_6TH` uploaded (see `scripts/bs_unito_download.py` and
`verdi data crystal_dft uploadfamily`).

Environment variables required for benchmarks and MPDS access:
- `MPDS_KEY` — MPDS API key.
- `YASCHEDULER_CONF_PATH` — path to the yascheduler config.
- `HOME` — must be set (benchmark templates are looked up under
  `$HOME/.aiida/mpds_aiida/`).

## OpenSpec change tracking

Spec-driven development is used under `openspec/` (`config.yaml`:
`schema: spec-driven`). Two changes have been worked on in this repository:

### Active change: `perovskite-benchmark-pipeline`

`openspec/changes/perovskite-benchmark-pipeline/` — fully implemented (all
tasks in `tasks.md` are checked off). Adds an end-to-end perovskite benchmark
pipeline. Artifacts:

- `proposal.md` — motivation and impact. Consolidates the previously ad-hoc
  scripts (`/data/perovskites/fetch_perovskites.py`,
  `scripts/aiida_submit_phase.py`, the yascheduler config, and the absolidix
  backend) into one reusable pipeline.
- `design.md` — decisions: package location `mpds_aiida/benchmark/`; CLI entry
  point `mpds-benchmark`; `BenchmarkReport` dataclass; synchronous polling of
  the AiiDA process every 30s; FLEUR `inp.xml` generated via `inpgen` on the
  remote; optional absolidix-backend API mode.
- `specs/perovskite-benchmark/spec.md` — requirements with scenarios:
  - Benchmark pipeline entry point (`formula/sg`, `--engine`, `--output`,
    `--timeout`, `--template`, `--absolidix-url`).
  - MPDS structure retrieval (minimal-atom-count, median cell vectors; reports
    `status: "no_structure"` with exit code 1 when no hits).
  - Benchmark templates (`benchmark_pcrystal.yml`, `benchmark_fleur.yml`,
    `--template` override).
  - AiiDA workchain submission + monitoring (Finished [0] / failed / timeout
    exit codes 0 / 1 / 2).
  - `BenchmarkReport` data model (fields: formula, sg, engine, engine_version,
    wall_time_s, scf_cycles, total_energy_ev, phonon_modes_gamma,
    elastic_constants {bulk/shear/young/poisson}, status, error, task_id,
    workchain_pk, timestamp).
  - Optional absolidix backend integration (`/calculations/create` +
    `/calculations/status` polling).
  - Environment validation (exit code 3 on missing `MPDS_KEY` or
    `YASCHEDULER_CONF_PATH`).
- `tasks.md` — 6 sections, all checked: scaffolding, benchmark templates,
  pipeline core, CLI, documentation (`scripts/README_benchmark.md`),
  testing (`test_benchmark_report.py`, `test_benchmark_cli.py`).

The implementation matches the spec: `mpds_aiida/benchmark/{cli,pipeline,report}.py`,
`mpds_aiida/calc_templates/benchmark_{pcrystal,fleur}.yml`, the CLI flags
(`--engine`, `--template`, `--output/-o`, `--timeout`, `--absolidix-url`),
the polling loop in `pipeline.run_benchmark` (30s sleep, terminal-state check,
deadline enforcement), and the `--engine both` mode with
`print_comparison_table` output.

When adding a new workflow features, follow the same OpenSpec workflow: create a
change folder under `openspec/changes/<name>/` with `proposal.md`,
`design.md`, `specs/<capability>/spec.md`, and `tasks.md`; archive completed
changes under `openspec/changes/archive/<YYYY-MM-DD>-<name>/`.

## Common tasks

### Install in editable mode (local venv at `.venv/`)
```shell
.venv/bin/pip install -e .
```

### Run the test suite
```shell
.venv/bin/pytest
# or scoped to the benchmark tests:
.venv/bin/pytest mpds_aiida/tests/test_benchmark_report.py mpds_aiida/tests/test_benchmark_cli.py -v
```
Tests rely on AiiDA fixtures from `conftest.py` (`aiida_profile`,
`new_database`, `new_workdir`); an isolated test profile is created
automatically. The benchmark unit tests (`test_benchmark_report.py`,
`test_benchmark_cli.py`) do not require external services.

### Run the benchmark CLI
```shell
.venv/bin/mpds-benchmark SrTiO3/221 --engine both -o report.json
.venv/bin/mpds-benchmark MgO/225 SrTiO3/221 LaMnO3/167 --engine pcrystal -o reports.json
.venv/bin/mpds-benchmark SrTiO3/221 --absolidix-url http://localhost:7050   # API mode
```
Phases are given as `formula/spacegroup`. Engines: `pcrystal` (default),
`fleur`, `both`. Default timeout 7200s. See `scripts/README_benchmark.md` for
the full usage reference and report JSON schema.

### Lint and format
Pre-commit is configured with `ruff` v0.15.8:
```shell
pre-commit run --all-files
# or directly:
ruff check --fix .
ruff format .
```

### Submit AiiDA workchains (manual)
Helper scripts live under `scripts/` (e.g. `aiida_submit_phase.py`,
`run_properties.py`, `run_seebeck_pipeline.py`). The benchmark pipeline is
the preferred replacement for these manual scripts.

## Conventions

### Implicit platform knowledge: AiiDA resources vs yascheduler dispatch vs FLEUR parallelism

The `resources` dict in a CalcJob submission and the actual compute layout
are **three different things read by three different layers**. Do not assume
the declared resources describe what runs:

- **aiida-fleur (third-party):** `num_mpiprocs_per_machine` is a
  *k-point-divisibility validation token*, not a resource request.
  `FleurBaseWorkChain.check_kpts`/`optimize_calc_options` rejects the
  submission with exit 390 when the declared MPI count does not divide the
  fleurinp k-point set; 1 MPI always passes (everything divides by 1). With
  `optimize_resources=True`, check_kpts **rewrites the declared value** to
  its own k-multiple before submission — even a correct declaration mutates.
  `add_comp_para.forbid_single_mpi` defaults to False; if it is set True,
  the 1-MPI recipe below rejects everything (exit 390).
- **AiiDA core:** logs `resources` as the scheduler resource request — a
  provenance artifact that *does not describe* what ran. Never audit a
  yac-submitted FLEUR calc's resources field to learn the real layout.
- **yascheduler:** **ignores the resources entirely**. Dispatch is strictly
  one-task-per-node (a node is busy while it has a RUNNING task; there is no
  per-CPU accounting). The real MPI/OMP layout is decided at dispatch time
  by the k-adaptive `[engine.fleur]` spawn in the yascheduler config
  (np = largest divisor of nkpt <= ncpus; OMP = ncpus/np).

**Standing FLEUR submission recipe (gate token only):**
`{'num_machines': 1, 'num_mpiprocs_per_machine': 1, 'optimize_resources': True}`
plus `add_comp_para.forbid_single_mpi=False`. At launch time, record the truth
in the workchain `metadata.description` (e.g. "real np/OMP decided by the
k-adaptive spawn at dispatch; the AiiDA resources field is gate-only").

Related dispatch caveat (yascheduler <= 1.8; fixed upstream in v3.0.0 by
claim-before-spawn): the busy-node set is updated only *after*
`start_task_on_machine` completes its SSH upload, so concurrent allocations
can race several tasks onto one node and collide. Do not bulk-unblock a
queue of same-engine tasks at once on older yascheduler versions.

- Code style is enforced by `ruff` (config in `.pre-commit-config.yaml`).
  Run `ruff check` and `ruff format` before committing. Pre-commit also runs
  `trailing-whitespace`, `check-toml`, `check-yaml`, `detect-private-key`, etc.
- Do not add new third-party dependencies without justification; prefer reusing
  `mpds_aiida.workflows`, `mpds_aiida.common`, and existing `calc_templates`.
- Calculation settings are YAML files under `mpds_aiida/calc_templates/`; new
  benchmark templates should follow the `benchmark_*.yml` naming pattern and
  pin settings for reproducibility (see `benchmark_pcrystal.yml` /
  `benchmark_fleur.yml`).
- AiiDA workchains must be registered as entry points in `pyproject.toml`
  under `[project.entry-points."aiida.workflows"]` and exported from
  `mpds_aiida/workflows/__init__.py`.
- Spec-driven changes are tracked under `openspec/`; the active change is
  `perovskite-benchmark-pipeline` (implemented, not yet archived). Follow the
  same OpenSpec workflow for new features.
- Version is sourced dynamically from `mpds_aiida.__version__`; bump it there
  (do not duplicate it in `pyproject.toml`). CI bumps via commitizen-style
  `Bump version` commits (see `git log`).

## Notes

- Do not commit secrets (`MPDS_KEY`, SSH keys). The pre-commit config includes
  `detect-private-key`.
- The `.venv/`, `__pycache__/`, `mpds_aiida.egg-info/`, and `.pytest_cache/`
  directories are build/test artifacts — do not edit by hand.
- AiiDA, yascheduler, and the simulation engines (CRYSTAL, FLEUR) are external
  services; assume they are already configured on the host rather than
  re-installing them. The remote compute node must have `inpgen` on PATH for
  FLEUR benchmarks.
- The benchmark pipeline is synchronous and polls AiiDA every 30s; acceptable
  for low-concurrency benchmark runs but not for high-throughput dispatch.
- The absolidix backend (`/data/absolidix/backend`) consumes this package via
  `mpds-aiida @ git+https://github.com/mpds-io/mpds-aiida`; breaking changes
  here affect that downstream.
