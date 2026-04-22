## Context

The mpds-aiida package provides AiiDA WorkChains for running CRYSTAL and FLEUR calculations triggered from MPDS data. Currently, users who want to compute a Seebeck coefficient from an MPDS structure must manually:

1. Submit `MPDSStructureWorkChain` (or another `MPDSCrystalWorkChain` subclass) for structure retrieval + CRYSTAL optimization
2. Wait for it to finish
3. Extract the crystal calculation UUID
4. Submit `MPDSPropertiesWorkChain` separately with that UUID

There is no single WorkChain that strings these steps together with proper error propagation.

The existing `MPDSCrystalWorkChain` already has an internal `run_properties_if_ready` step that launches `MPDSPropertiesWorkChain` after the SCF succeeds, but this is coupled to the internal YAML template system and calculation queue. The user's request is for a **new top-level WorkChain** that explicitly orchestrates optimization → Seebeck in two sequential phases, making the pipeline easier to submit, track, and debug.

Key existing code:
- `MPDSCrystalWorkChain` (`crystal.py`): manages a priority queue of CRYSTAL calculations (optimization, SCF, etc.) and conditionally runs properties afterward.
- `MPDSStructureWorkChain` (`mpds.py`): subclass that fetches geometry from MPDS API.
- `MPDSPropertiesWorkChain` (`properties.py`): wraps `CustomPropertiesWorkChain`, takes a `crystal_calc_uuid` and `code`, extracts `fort.9`, runs properties.
- `AiidaStructureWorkChain` (`aiida.py`): subclass that uses an AiiDA `StructureData` directly.

## Goals / Non-Goals

**Goals:**
- Provide a single `MPDSCrystalSeebeckWorkChain` that sequentially runs `MPDSCrystalWorkChain` (or its subclass) and then `MPDSPropertiesWorkChain`
- If the crystal optimization or any child chain fails, **abort the pipeline** and never launch the properties step
- Expose combined outputs from both sub-workchains
- Follow AiiDA WorkChain conventions (outline, spec, exit codes, `submit`/`to_context`)
- Register as an AiiDA entry point for discoverability

**Non-Goals:**
- Modifying existing `MPDSCrystalWorkChain` or `MPDSPropertiesWorkChain` internals
- Supporting FLEUR-based calculations (that's a separate pipeline)
- Parallel execution of the two phases (they are inherently sequential)
- Customizing the template/calculations configuration beyond what the sub-workchains accept

## Decisions

### 1. Composition via `submit` + `to_context` (AiiDA standard pattern)

The new WorkChain uses `self.submit()` and `self.to_context()` to launch each sub-workchain asynchronously. This is the standard AiiDA pattern for orchestrating WorkChains and ensures correct provenance tracking.

**Alternative considered**: Using `while_` loop with step functions for each phase. Rejected because the two phases are purely sequential with a hard guard — a simple linear outline is clearer.

### 2. Two-step outline with `if_` guard

```
spec.outline(
    cls.run_crystal,
    cls.check_crystal,
    if_(cls.should_run_properties)(
        cls.run_properties,
        cls.finalize_properties,
    ),
)
```

The `if_` guard on `should_run_properties` checks whether the crystal WorkChain finished OK. If not, the pipeline stops cleanly without launching properties.

### 3. WorkChain class hierarchy

`MPDSCrystalSeebeckWorkChain` will **not** subclass `MPDSCrystalWorkChain`. It will be a standalone WorkChain that *composes* the two existing chains. This avoids inheriting the calculation queue machinery that is irrelevant to this pipeline.

### 4. Input delegation

Inputs for the crystal phase (`workchain_options`, `mpds_query`/`structure`, `check_for_bond_type`) and properties phase (`code`, `parameters`, `options`) will be accepted directly by the new WorkChain and forwarded to the sub-workchains. The `crystal_calc_uuid` input of `MPDSPropertiesWorkChain` will be automatically resolved from the crystal sub-workchain's output.

### 5. Exit codes

The WorkChain will define exit codes for:
- All exit codes from the crystal phase (re-exposed or mapped)
- A new `ERROR_PROPERTIES_FAILED` code for when the properties step fails
- Propagating the crystal failure exit code so callers know why properties were skipped

## Risks / Trade-offs

- **Risk**: `MPDSCrystalWorkChain` has complex internal state (calculation queue, template system) that could make input forwarding tricky → **Mitigation**: Use `get_builder()` and pass inputs through directly; don't replicate internal logic
- **Risk**: The `MPDSPropertiesWorkChain` currently takes `crystal_calc_uuid` (a `Str`) pointing to a `CalcJobNode`, but from `MPDSCrystalWorkChain` we get a WorkChain node, not a CalcJobNode → **Mitigation**: In the new pipeline, extract the relevant `CalcJobNode` from the crystal WorkChain's called descendents, or pass the wavefunction directly
- **Risk**: Different subclasses of `MPDSCrystalWorkChain` (`MPDSStructureWorkChain`, `AiidaStructureWorkChain`) have different required inputs → **Mitigation**: Accept a `crystal_workchain` input (a `Str` with the entry point name) that selects which subclass to use, OR make subclass-specific variants