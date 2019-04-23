
import pytest
import os
from mpds_aiida_workflows.tests import TEST_DIR


@pytest.fixture
def test_computer(aiida_profile, new_workdir):
    from aiida.common.exceptions import NotExistent
    try:
        computer = aiida_profile._backend.computers.get(name='localhost')
    except NotExistent:
        computer = aiida_profile._backend.computers.create(
                name='localhost',
                description='localhost computer set up by aiida_crystal tests',
                hostname='localhost',
                workdir=new_workdir,
                transport_type='local',
                scheduler_type='direct',
                enabled_state=True)
    computer.store()
    authinfo = aiida_profile._backend.authinfos.create(computer=computer,
                                                       user=aiida_profile._backend.users.get_automatic_user())
    authinfo.store()
    return computer


@pytest.fixture
def test_crystal_code(test_computer):
    from aiida.orm import Code
    if not test_computer.pk:
        test_computer.store()
    code = Code()
    code.label = 'crystal'
    code.description = 'CRYSTAL code'
    mock_exec = os.path.join(TEST_DIR, 'mock', 'crystal')
    code.set_remote_computer_exec((test_computer, mock_exec))
    code.set_input_plugin_name('crystal.serial')
    return code


@pytest.fixture
def test_properties_code(test_computer):
    from aiida.orm import Code
    if not test_computer.pk:
        test_computer.store()
    code = Code()
    code.label = 'properties'
    code.description = 'CRYSTAL properties code'
    code.set_remote_computer_exec((test_computer, '/usr/local/bin/properties'))
    code.set_input_plugin_name('crystal.properties')
    return code


@pytest.fixture
def crystal_calc_parameters():
    from aiida.orm.data.parameter import ParameterData
    return ParameterData(dict={
        "title": "Crystal calc",
        "scf": {
            "k_points": (8, 8)
        },
        "geometry": {
            "optimise": {
                "type": "FULLOPTG"
            },
            "frequency": {
                "ir": {
                    "type": "INTCPHF"
                },
                "raman": True
            },
            "elastic": {
                "type": "ELASTCON"
            }
        }
    })


@pytest.fixture
def properties_calc_parameters():
    from aiida.orm.data.parameter import ParameterData
    return ParameterData(dict={
        "band": {
            "shrink": 8,
            "k_points": 30,
        },
        "dos": {
            "n_e": 100
        }
    })


@pytest.fixture
def test_basis(aiida_profile):
    from aiida.common.exceptions import NotExistent
    from mpds_aiida_workflows.tests import TEST_DIR
    from aiida_crystal.data.basis_set import BasisSetData
    upload_basisset_family = BasisSetData.upload_basisset_family
    try:
        BasisSetData.get_basis_group('sto-3g')
    except NotExistent:
        upload_basisset_family(
            os.path.join(TEST_DIR, "basis"),
            "sto-3g",
            "minimal basis sets",
            stop_if_existing=True,
            extension=".basis")

    return BasisSetData.get_basis_group_map('sto-3g')
