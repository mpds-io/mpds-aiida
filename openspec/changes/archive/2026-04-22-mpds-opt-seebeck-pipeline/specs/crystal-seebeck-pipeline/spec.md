## ADDED Requirements

### Requirement: Sequential pipeline execution
The `MPDSCrystalSeebeckWorkChain` SHALL execute `MPDSCrystalWorkChain` first and `MPDSPropertiesWorkChain` second, in strict sequential order. The properties step SHALL NOT begin until the crystal step has completed.

#### Scenario: Normal pipeline execution
- **WHEN** the WorkChain is submitted with valid inputs for both phases
- **THEN** it SHALL first submit `MPDSCrystalWorkChain`, wait for it to finish, and only then submit `MPDSPropertiesWorkChain`

#### Scenario: Crystal step is still running
- **WHEN** `MPDSCrystalWorkChain` has been submitted but not yet completed
- **THEN** the WorkChain SHALL wait and SHALL NOT submit `MPDSPropertiesWorkChain`

### Requirement: Error propagation blocks properties step
If `MPDSCrystalWorkChain` or any of its child workchains finishes with an error (non-zero exit status or `is_finished_ok == False`), the pipeline SHALL NOT launch `MPDSPropertiesWorkChain`. The WorkChain SHALL exit with an appropriate error code indicating the crystal phase failed.

#### Scenario: Crystal optimization fails
- **WHEN** `MPDSCrystalWorkChain` returns an exit code (e.g., `ERROR_OPTIMIZATION_FAILED`)
- **THEN** the WorkChain SHALL skip the properties step and return the crystal exit code

#### Scenario: Crystal workchain finishes not OK
- **WHEN** `MPDSCrystalWorkChain` completes with `is_finished_ok == False` but no specific exit code
- **THEN** the WorkChain SHALL skip the properties step and return `ERROR_CRYSTAL_FAILED`

#### Scenario: Crystal workchain succeeds
- **WHEN** `MPDSCrystalWorkChain` completes with `is_finished_ok == True`
- **THEN** the WorkChain SHALL proceed to launch `MPDSPropertiesWorkChain`

### Requirement: WorkChain inputs
The `MPDSCrystalSeebeckWorkChain` SHALL accept the following inputs, forwarding them to the appropriate sub-workchain:

- `workchain_options` (Dict, optional): forwarded to the crystal WorkChain
- `mpds_query` (Dict, optional): if provided, use `MPDSStructureWorkChain` as the crystal step
- `structure` (StructureData, optional): if provided (and `mpds_query` is not), use `AiidaStructureWorkChain` as the crystal step
- `check_for_bond_type` (Bool, optional): forwarded to the crystal WorkChain
- `properties_code` (Code, required): the CRYSTAL Properties code, forwarded to `MPDSPropertiesWorkChain`
- `properties_parameters` (Dict, optional): forwarded to `MPDSPropertiesWorkChain`
- `properties_options` (Dict, optional): forwarded to `MPDSPropertiesWorkChain`

Exactly one of `mpds_query` or `structure` SHALL be provided (not both, not neither).

#### Scenario: Submitting with MPDS query
- **WHEN** `mpds_query` is provided and `structure` is not
- **THEN** the crystal step SHALL use `MPDSStructureWorkChain` with the query

#### Scenario: Submitting with AiiDA structure
- **WHEN** `structure` is provided and `mpds_query` is not
- **THEN** the crystal step SHALL use `AiidaStructureWorkChain` with the structure

#### Scenario: Both or neither structure input provided
- **WHEN** both `mpds_query` and `structure` are provided, or neither is provided
- **THEN** the WorkChain SHALL return `INPUT_ERROR` exit code

### Requirement: Combined outputs
The WorkChain SHALL expose all outputs from both sub-workchains using AiiDA's `expose_outputs` mechanism:

- All outputs from `MPDSCrystalWorkChain` (excluding `output_parameters`) in a `crystal` namespace
- All outputs from `MPDSPropertiesWorkChain` in a `properties` namespace
- `output_parameters` from the crystal step in a `crystal.output_parameters` dynamic namespace

#### Scenario: Both steps succeed
- **WHEN** both crystal and properties steps finish successfully
- **THEN** the WorkChain SHALL expose outputs from both in their respective namespaces

#### Scenario: Crystal succeeds but properties fails
- **WHEN** crystal step succeeds but properties step fails
- **THEN** the WorkChain SHALL still expose the crystal outputs in the `crystal` namespace

### Requirement: Exit codes
The WorkChain SHALL define the following exit codes:

- `410`: `INPUT_ERROR` — invalid or conflicting inputs
- `411`: `ERROR_INVALID_ENGINE` — non-existent code is given
- `450`: `ERROR_CRYSTAL_FAILED` — the crystal WorkChain did not finish OK (generic failure)
- `412`: `ERROR_OPTIMIZATION_FAILED` — forwarded from crystal step when optimization specifically fails
- `460`: `ERROR_NO_RETRIEVED` — the crystal calculation does not contain a retrieved folder
- `461`: `ERROR_NO_FORT9` — `fort.9` wavefunction not found in the retrieved folder
- `451`: `ERROR_PROPERTIES_FAILED` — the properties WorkChain did not finish OK

#### Scenario: Exit code from crystal step
- **WHEN** the crystal WorkChain exits with a non-zero exit status
- **THEN** the pipeline SHALL map known exit codes (410, 412) directly and return `ERROR_CRYSTAL_FAILED` (450) for unknown errors

#### Scenario: Exit code from properties step
- **WHEN** the properties WorkChain exits with `is_finished_ok == False`
- **THEN** the pipeline SHALL return `ERROR_PROPERTIES_FAILED` (451)

#### Scenario: Missing retrieved folder
- **WHEN** `MPDSPropertiesWorkChain` is provided with a `crystal_calc_uuid` pointing to a calculation that has no `retrieved` output folder
- **THEN** it SHALL return `ERROR_NO_RETRIEVED` (460)

#### Scenario: Missing wavefunction file
- **WHEN** `MPDSPropertiesWorkChain` resolves `crystal_calc_uuid` and the `retrieved` folder does not contain `fort.9`
- **THEN** it SHALL return `ERROR_NO_FORT9` (461)

### Requirement: Wavefunction hand-off
The WorkChain SHALL automatically extract the `fort.9` wavefunction file from the **last** (SCF) CalcJob in the crystal step's output and pass it to the `MPDSPropertiesWorkChain` as a `SinglefileData` input, without requiring the user to provide a `crystal_calc_uuid`. The wavefunction from the final SCF step (not the optimization step) is required for Seebeck calculations.

#### Scenario: Extracting wavefunction from crystal step
- **WHEN** the crystal step finishes OK and has a `retrieved` folder containing `fort.9`
- **THEN** the WorkChain SHALL extract `fort.9` from the last CalcJob with an available wavefunction (SCF step) as a `SinglefileData` node and pass it to the properties step

#### Scenario: Missing wavefunction
- **WHEN** the crystal step finishes OK but no wavefunction is available in its outputs
- **THEN** the WorkChain SHALL return `ERROR_CRYSTAL_FAILED` (450) with a descriptive report message

### Requirement: AiiDA entry point registration
The `MPDSCrystalSeebeckWorkChain` SHALL be registered as an AiiDA workflow entry point with name `crystal.mpds_seebeck` in `pyproject.toml`.

#### Scenario: Discovering the WorkChain
- **WHEN** a user runs `aiida-workflow list` or uses `WorkflowFactory('crystal.mpds_seebeck')`
- **THEN** the `MPDSCrystalSeebeckWorkChain` SHALL be discoverable and loadable

### Requirement: BoltzTraP output file preservation
The `CustomPropertiesWorkChain` SHALL extract and save BoltzTraP output files from the `retrieved` folder of the Properties CalcJob as `SinglefileData` nodes. The following files SHALL be preserved:

- `SEEBECK.DAT` — Seebeck coefficient data
- `SIGMAS.DAT` — electrical conductivity data
- `KAPPA.DAT` — thermal conductivity data
- `TDF.DAT` — transport distribution function data

These outputs SHALL be exposed as `seebeck_dat`, `sigmas_dat`, `kappa_dat`, and `tdf_dat` respectively, and included in the `properties` namespace of the `MPDSCrystalSeebeckWorkChain`.

#### Scenario: BoltzTraP files present in retrieved
- **WHEN** the Properties calculation finishes OK and BoltzTraP output files are present in the `retrieved` folder
- **THEN** the WorkChain SHALL save each file as a `SinglefileData` node and expose it as an output

#### Scenario: BoltzTraP files absent
- **WHEN** the Properties calculation finishes OK but BoltzTraP output files are not present
- **THEN** the corresponding outputs SHALL be omitted (required=False)

### Note
This pipeline was designed with assistance from GLM-5.1 (ollama-cloud/glm-5.1).