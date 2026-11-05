from types import SimpleNamespace as NS

import pytest
from ase import Atoms
from mpds_aiida.workflows import abacus_base as base
from mpds_aiida.workflows.abacus_mpds import matches_composition


@pytest.mark.parametrize(
    "formula,expected",
    [("Ca4O12Ti4", True), ("Ca4O11Ti4", False), ("Ca8O24Ti8", True), ("CaTiO3", True)],
)
def test_actual_composition(formula, expected):
    assert matches_composition(Atoms(formula), "CaTiO3") is expected


@pytest.mark.parametrize("phonons,expected", [(False, True), (True, False)])
def test_scf_decision_preserves_phonons_without_relaxation(phonons, expected):
    process = NS(ctx=NS(calculation="scf", need_phonons=phonons, optimize=False))
    assert base.MPDSAbacusWorkChain.need_scf(process) is expected


@pytest.mark.parametrize(
    "finished,log,error",
    [
        (False, "#SCF IS CONVERGED#", "ERROR_SCF_FAILED"),
        (True, "not converged", "ERROR_SCF_NOT_CONVERGED"),
        (True, "#SCF IS CONVERGED#", None),
    ],
)
def test_scf_inspection(monkeypatch, finished, log, error):
    monkeypatch.setattr(base, "read_scf_log", lambda calc: log)
    misc = NS(creator=object())
    outputs = []
    process = NS(
        ctx=NS(scf=NS(is_finished_ok=finished, outputs=NS(misc=misc))),
        exit_codes=base.MPDSAbacusWorkChain.exit_codes,
        out=lambda key, value: outputs.append((key, value)),
        report=lambda msg: None,
    )
    result = base.MPDSAbacusWorkChain.inspect_scf(process)
    if error:
        assert result == getattr(process.exit_codes, error)
        assert outputs == []
    else:
        assert result is None
        assert outputs == [("output_scf", misc)]


def test_scf_submission_uses_base_builder(monkeypatch, tmp_path):
    from aiida import orm
    from aiida.manage import get_manager
    from aiida.storage.sqlite_temp import SqliteTempBackend

    backend = SqliteTempBackend(SqliteTempBackend.create_profile())
    monkeypatch.setattr(get_manager(), "get_profile_storage", lambda: backend)
    try:
        structure = orm.StructureData(cell=[[5, 0, 0], [0, 5, 0], [0, 0, 5]])
        structure.append_atom(position=[0, 0, 0], symbols="Si")
        computer = orm.Computer(
            label="test",
            hostname="localhost",
            transport_type="core.local",
            scheduler_type="core.direct",
            workdir="/tmp/test",
        ).store()
        code = orm.InstalledCode(computer=computer, filepath_executable="/bin/true")
        monkeypatch.setattr(base, "load_code", lambda label: code)
        from aiida_pseudo.groups.family import PseudoPotentialFamily

        PseudoPotentialFamily(label="test-family").store()
        submitted = []
        process = NS(
            ctx=NS(
                structure=structure,
                phase_label="Si",
                codes={"abacus": "abacus@yascheduler"},
                options_run={
                    "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1}
                },
                config={
                    "options": {"pseudo_family": "test-family", "kpoints": [2, 2, 2]},
                    "default": {"scf": {"input": {"ecutwfc": 100}}},
                },
            ),
            submit=lambda builder: submitted.append(builder) or NS(pk=1),
        )
        base.MPDSAbacusWorkChain.run_scf(process)
        assert len(submitted) == 1
        builder = submitted[0]
        assert builder.abacus.structure is structure
        assert builder.abacus.parameters.get_dict()["input"]["calculation"] == "scf"
        assert builder.kpoints.get_kpoints_mesh()[0] == [2, 2, 2]
        assert builder.abacus.settings.get_dict()["flat_output"] is True
        assert builder.pseudo_family.value == "test-family"
        assert base.AbacusBaseWorkChain.spec().inputs.validate(dict(builder)) is None
    finally:
        backend.close()


@pytest.mark.parametrize("valid", [False, True])
def test_geometry_filters_before_selecting(monkeypatch, valid):
    import aiida.plugins
    from mpds_aiida.workflows import abacus_mpds as module

    wrong = Atoms("Ca4O11Ti4", cell=[5, 5, 5])
    right = Atoms("Ca8O24Ti8", cell=[10, 10, 10])
    structures = [wrong, right] if valid else [wrong]
    client = NS(
        get_data=lambda *args, **kwargs: structures,
        compile_crystal=lambda line, **kwargs: line,
    )
    monkeypatch.setenv("MPDS_KEY", "test")
    monkeypatch.setattr(module, "MPDSDataRetrieval", lambda **kwargs: client)
    monkeypatch.setattr(aiida.plugins, "DataFactory", lambda name: lambda ase: ase)
    process = NS(
        inputs=NS(mpds_query=NS(get_dict=lambda: {"formulae": "CaTiO3", "sgs": 62})),
        exit_codes=module.MPDSAbacusStructureWorkChain.exit_codes,
    )
    result = module.MPDSAbacusStructureWorkChain.get_geometry(process)
    if valid:
        assert result is right
    else:
        assert result == process.exit_codes.ERROR_COMPOSITION_MISMATCH
