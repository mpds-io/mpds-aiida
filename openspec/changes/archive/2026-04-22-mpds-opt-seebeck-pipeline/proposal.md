## Why

Currently, the optimization of a crystal structure via `MPDSCrystalWorkChain` and the subsequent Seebeck coefficient calculation via `MPDSPropertiesWorkChain` must be launched and managed separately. There is no single AiiDA WorkChain that orchestrates both steps with proper error propagation — if the optimization fails, the properties step should never start, but today this guard is not enforced at the workflow level. A unified pipeline is needed to automate the full sequence from raw MPDS structure to Seebeck result, while respecting AiiDA's provenance and error-handling conventions.

## What Changes

- Add a new `MPDSCrystalSeebeckWorkChain` that sequentially runs `MPDSCrystalWorkChain` (structure retrieval + optimization) and then `MPDSPropertiesWorkChain` (Seebeck/band-structure calculation)
- If `MPDSCrystalWorkChain` or any of its child workchains finishes with an error, the pipeline must abort and **not** launch `MPDSPropertiesWorkChain`
- The new WorkChain must expose the combined outputs from both sub-workchains (optimized structure, output parameters, properties results)
- Register the new WorkChain as an AiiDA entry point so it can be discovered and submitted via `aiida.engine.submit`

## Capabilities

### New Capabilities
- `crystal-seebeck-pipeline`: A WorkChain that orchestrates the full MPDS→CRYSTAL optimization→Seebeck properties pipeline with error-guarded sequential execution

### Modified Capabilities

_(none — no existing specs are being modified)_

## Impact

- **New file**: `mpds_aiida/workflows/crystal_seebeck.py` containing the `MPDSCrystalSeebeckWorkChain`
- **Modified file**: `pyproject.toml` — add entry point for the new workflow under `[project.entry-points."aiida.workflows"]`
- **Modified file**: `mpds_aiida/workflows/__init__.py` — export the new WorkChain class
- **Dependencies**: Relies on existing `MPDSCrystalWorkChain` and `MPDSPropertiesWorkChain`; no new external dependencies