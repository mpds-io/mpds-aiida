"""Force validation independent of pseudopotential-family selection."""

from types import SimpleNamespace

import numpy as np
import pytest

from mpds_aiida.abacus_forces import (
    read_scf_log,
    restore_force_order,
    scf_has_converged,
)


@pytest.mark.parametrize(
    "log,expected",
    [
        ("ABACUS v3.11\n#SCF IS CONVERGED#\n", True),
        ("ABACUS v3.11\nforces exist but no convergence\n", False),
        ("#SCF IS CONVERGED#\nABACUS v3.11\nfailed to start\n", False),
        ("#SCF IS CONVERGED#\n#SCF IS NOT CONVERGED#\n", False),
        ("#SCF IS CONVERGED#\nconvergence has NOT been achieved\n", False),
        (
            "ABACUS v3.11\n#SCF IS NOT CONVERGED#\nABACUS v3.11\n#SCF IS CONVERGED#\n",
            True,
        ),
        ("", False),
    ],
)
def test_final_scf_convergence_required(log, expected):
    assert scf_has_converged(log) is expected


@pytest.mark.parametrize(
    "layout",
    [
        "running_scf.log",
        "OUT.aiida/running_scf.log",
        "OUT.custom/running_scf.log",
        None,
    ],
)
def test_scf_log_layout(layout):
    def read(filename):
        if filename == layout:
            return "#SCF IS CONVERGED#"
        raise FileNotFoundError(filename)

    calculation = SimpleNamespace(
        inputs=SimpleNamespace(
            parameters=SimpleNamespace(
                get_dict=lambda: {
                    "input": {
                        "suffix": "custom"
                        if layout == "OUT.custom/running_scf.log"
                        else "aiida"
                    }
                }
            )
        ),
        outputs=SimpleNamespace(
            retrieved=SimpleNamespace(
                base=SimpleNamespace(
                    repository=SimpleNamespace(get_object_content=read)
                )
            )
        ),
    )
    if layout is None:
        with pytest.raises(FileNotFoundError):
            read_scf_log(calculation)
    else:
        assert scf_has_converged(read_scf_log(calculation))


def test_direct_coordinates_and_nonunit_lattice_scale():
    structure = SimpleNamespace(
        cell=(np.eye(3) * 2).tolist(),
        sites=[
            SimpleNamespace(kind_name="O", position=[1, 0, 0]),
            SimpleNamespace(kind_name="Y", position=[0, 1, 0]),
            SimpleNamespace(kind_name="O", position=[0, 0, 1]),
        ],
    )
    stru = """LATTICE_CONSTANT
3.779452250915656
LATTICE_VECTORS
1 0 0
0 1 0
0 0 1
ATOMIC_POSITIONS
Direct
O
0
2
0.5 0 0
0 0 0.5
Y
0
1
0 0.5 0
"""
    forces, permutation = restore_force_order(
        structure, [[1, 0, 0], [3, 0, 0], [2, 0, 0]], stru
    )
    assert permutation == [0, 2, 1]
    assert forces == [[1, 0, 0], [2, 0, 0], [3, 0, 0]]


def structure():
    return SimpleNamespace(
        cell=np.eye(3).tolist(),
        sites=[
            SimpleNamespace(kind_name="O", position=[0, 0, 0]),
            SimpleNamespace(kind_name="Y", position=[0.2, 0, 0]),
            SimpleNamespace(kind_name="O", position=[0.4, 0, 0]),
            SimpleNamespace(kind_name="Al", position=[0.6, 0, 0]),
        ],
    )


STRU = """LATTICE_CONSTANT
1.889726125457828
LATTICE_VECTORS
1 0 0
0 1 0
0 0 1
ATOMIC_POSITIONS
Cartesian
O
0
2
0 0 0 m 1 1 1
0.4 0 0 m 1 1 1
Y
0
1
0.2 0 0 m 1 1 1
Al
0
1
0.6 0 0 m 1 1 1
"""


def test_interleaved_oxygen_force_rows():
    forces, permutation = restore_force_order(
        structure(), [[1, 0, 0], [3, 0, 0], [2, 0, 0], [4, 0, 0]], STRU
    )
    assert permutation == [0, 2, 1, 3]
    np.testing.assert_equal(forces, [[1, 0, 0], [2, 0, 0], [3, 0, 0], [4, 0, 0]])


@pytest.mark.parametrize(
    "forces", [np.zeros((3, 3)), np.zeros((4, 2)), np.full((4, 3), np.nan)]
)
def test_invalid_force_arrays_rejected(forces):
    with pytest.raises(ValueError):
        restore_force_order(structure(), forces, STRU)


@pytest.mark.parametrize(
    "content",
    [
        STRU.replace("0.4 0 0 m", "0 0 0 m"),
        STRU.replace("Cartesian", "Cartesian_au"),
        STRU.replace("0.6 0 0 m", "0.7 0 0 m"),
        STRU.replace("1.889726125457828", "2.0"),
    ],
)
def test_inconsistent_stru_rejected(content):
    with pytest.raises(ValueError):
        restore_force_order(structure(), np.zeros((4, 3)), content)


def test_force_workflow_stores_new_output_data(monkeypatch):
    """AiiDA refuses unstored Data returned from a WorkChain, even after SCF succeeds."""
    from mpds_aiida.workflows import abacus_phonopy as module

    class Data:
        def __init__(self, dict):
            self.value = dict
            self.is_stored = False

        def store(self):
            self.is_stored = True
            return self

        def get_dict(self):
            return self.value

    monkeypatch.setattr(module, "Dict", Data)
    misc = Data(
        {
            "final_forces": [[1, 0, 0], [3, 0, 0], [2, 0, 0], [4, 0, 0]],
            "force_unit": "eV/Angstrom",
        }
    ).store()
    misc.creator = SimpleNamespace(
        uuid="source-calculation",
        inputs=SimpleNamespace(parameters=Data({"input": {"calculation": "scf"}})),
        base=SimpleNamespace(
            repository=SimpleNamespace(get_object_content=lambda name: STRU)
        ),
    )
    outputs = {}

    def out(name, value):
        assert value.is_stored, f"Cannot return unstored output {name} from WorkChain"
        outputs[name] = value.get_dict()

    workflow = SimpleNamespace(
        ctx=SimpleNamespace(scf=SimpleNamespace(outputs=SimpleNamespace(misc=misc))),
        inputs=SimpleNamespace(
            structure=structure(), structure_label=SimpleNamespace(value="1")
        ),
        out=out,
    )
    module.AbacusForcesWorkChain.finalize(workflow)
    assert outputs["force_order"] == {
        "abacus_to_structure": [0, 2, 1, 3],
        "source_calcjob_uuid": "source-calculation",
    }
    assert outputs["forces"]["forces_1"] == [[1, 0, 0], [2, 0, 0], [3, 0, 0], [4, 0, 0]]
