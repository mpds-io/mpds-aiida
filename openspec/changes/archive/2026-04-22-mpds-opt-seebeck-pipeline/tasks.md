## 1. Create WorkChain module

- [x] 1.1 Create `mpds_aiida/workflows/crystal_seebeck.py` with `MPDSCrystalSeebeckWorkChain` class skeleton (imports, `define` method with spec)
- [x] 1.2 Implement `define` method: declare all inputs (`workchain_options`, `mpds_query`, `structure`, `check_for_bond_type`, `properties_code`, `properties_parameters`, `properties_options`), outline (`run_crystal` → `check_crystal` → `if_(should_run_properties)` → `run_properties` → `finalize_properties`), expose outputs, and define exit codes
- [x] 1.3 Implement `run_crystal` step: validate that exactly one of `mpds_query`/`structure` is provided, build inputs for the chosen subclass (`MPDSStructureWorkChain` or `AiidaStructureWorkChain`), submit, and store in `to_context`
- [x] 1.4 Implement `check_crystal` step: check `is_finished_ok` on crystal WorkChain, store wavefunction from crystal outputs if available, set `ctx.ready_for_properties` flag or return exit code
- [x] 1.5 Implement `should_run_properties` step: return `ctx.ready_for_properties` boolean
- [x] 1.6 Implement `run_properties` step: extract `fort.9` as `SinglefileData` from crystal WorkChain's called descendents, build inputs for `MPDSPropertiesWorkChain` (with `code`, `wavefunction`, optional `parameters`/`options`), submit, store in `to_context`
- [x] 1.7 Implement `finalize_properties` step: check `is_finished_ok` on properties WorkChain, expose outputs from both sub-workchains into their respective namespaces (`crystal.*`, `properties.*`), return error exit code if properties failed

## 2. Wavefunction hand-off logic

- [x] 2.1 Implement wavefunction extraction: walk crystal WorkChain's `called` descendents to find the `CalcJobNode` with `retrieved` containing `fort.9`, create `SinglefileData` from it
- [x] 2.2 Handle missing wavefunction case: if crystal WorkChain finished OK but no wavefunction found, report error and return `ERROR_CRYSTAL_FAILED`

## 3. Error propagation

- [x] 3.1 Map known crystal exit codes (410, 411, 412) directly; return `ERROR_CRYSTAL_FAILED` (450) for unknown crystal failures
- [x] 3.2 Return `ERROR_PROPERTIES_FAILED` (451) if properties step fails
- [x] 3.3 Ensure no properties submission occurs when crystal step has any error

## 4. Registration and exports

- [x] 4.1 Add entry point `"crystal.mpds_seebeck" = "mpds_aiida.workflows.crystal_seebeck:MPDSCrystalSeebeckWorkChain"` to `pyproject.toml` under `[project.entry-points."aiida.workflows"]`
- [x] 4.2 Add `MPDSCrystalSeebeckWorkChain` import to `mpds_aiida/workflows/__init__.py`

## 5. Validation

- [x] 5.1 Verify the WorkChain can be loaded via `WorkflowFactory('crystal.mpds_seebeck')`
- [x] 5.2 Run `python -c "from mpds_aiida.workflows.crystal_seebeck import MPDSCrystalSeebeckWorkChain"` to check imports
- [x] 5.3 Verify `define` method doesn't raise errors by instantiating the spec