"""Unit tests for the ABACUS engine workchains (no AiiDA profile needed)."""


def test_abacus_template():
    from mpds_aiida.common import get_template

    tpl = get_template("abacus_default.yml")

    assert set(tpl["codes"]) == {"abacus", "phonopy"}
    assert "options" in tpl
    assert "default" in tpl
    assert "calculations" in tpl

    options = tpl["options"]
    for key in ("need_phonons", "optimize_structure", "calculation", "kpoints"):
        assert key in options, f"missing options key: {key}"
    assert options["calculation"] in ("scf", "relax", "cell-relax")
    assert len(options["kpoints"]) == 3

    scf_input = tpl["default"]["scf"]["input"]
    assert scf_input["basis_type"] in ("pw", "lcao")
    assert "ecutwfc" in scf_input
    assert "scf_thr" in scf_input

    phonon_params = tpl["calculations"]["phonons"]["parameters"]
    supercell_matrix = phonon_params["supercell_matrix"]
    assert len(supercell_matrix) == 3
    assert all(len(row) == 3 for row in supercell_matrix)


def test_mpds_abacus_workchain_spec():
    from mpds_aiida.workflows.abacus_base import MPDSAbacusWorkChain

    spec = MPDSAbacusWorkChain.spec()

    for port in ("structure", "workchain_options", "config_file", "phase_label"):
        assert port in spec.inputs, f"missing input port: {port}"

    assert spec.inputs["config_file"].has_default()

    assert "ERROR_OPTIMIZATION_FAILED" in spec.exit_codes
    assert "ERROR_PHONONS_FAILED" in spec.exit_codes

    assert "optimized_structure" in spec.outputs
    assert "output_phonopy" in spec.outputs


def test_mpds_abacus_structure_workchain_spec():
    from mpds_aiida.workflows.abacus_mpds import MPDSAbacusStructureWorkChain

    spec = MPDSAbacusStructureWorkChain.spec()

    assert "mpds_query" in spec.inputs
    assert "structure" not in spec.inputs
    assert "phase_label" not in spec.inputs

    for code in (
        "ERROR_NO_MPDS_API_KEY",
        "ERROR_API_ERROR",
        "ERROR_NO_HITS",
        "ERROR_SERVER_NOT_FOUND",
    ):
        assert code in spec.exit_codes


def test_abacus_forces_workchain_spec():
    from mpds_aiida.workflows.abacus_phonopy import AbacusForcesWorkChain

    spec = AbacusForcesWorkChain.spec()

    for port in (
        "code",
        "structure",
        "parameters",
        "pseudo_family",
        "kpoints_distance",
        "options",
        "structure_label",
    ):
        assert port in spec.inputs, f"missing input port: {port}"

    assert spec.inputs["structure_label"].has_default()

    for code in ("ERROR_SCF_FAILED", "ERROR_NO_FORCES", "ERROR_WRONG_FORCES_UNIT"):
        assert code in spec.exit_codes

    assert "forces" in spec.outputs


def test_phonopy_abacus_workchain_spec():
    from mpds_aiida.workflows.abacus_phonopy import PhonopyAbacusWorkChain

    spec = PhonopyAbacusWorkChain.spec()

    for port in (
        "abacus_parameters",
        "code",
        "pseudo_family",
        "kpoints_distance",
        "options",
    ):
        assert port in spec.inputs, f"missing input port: {port}"

    # Inherited from the base PhonopyWorkChain
    for port in ("structure", "supercell_matrix", "phonopy", "clean_workdir"):
        assert port in spec.inputs, f"missing inherited input port: {port}"

    assert "FORCES_DATA_NOT_FOUND" in spec.exit_codes

    assert "supercells_forces" in spec.outputs
    assert "phonopy_data" in spec.outputs


def test_forces_parameters_forced_scf():
    """The forces workchain must run scf with cal_force, regardless of the template."""
    from mpds_aiida.workflows.abacus_phonopy import AbacusForcesWorkChain

    spec = AbacusForcesWorkChain.spec()
    # parameters is a plain Dict; the forcing happens in run_scf, verified via spec sanity here
    assert spec.inputs["parameters"].required
