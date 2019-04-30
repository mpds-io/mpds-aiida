
# noinspection PyUnresolvedReferences
from mpds_aiida_workflows.tests.fixtures import *


def test_workchain_run(test_crystal_code,
                       crystal_calc_parameters,
                       test_properties_code,
                       properties_calc_parameters,
                       test_basis):
    from mpds_aiida_workflows.crystal import MPDSCrystalWorkchain
    from aiida.orm import DataFactory
    from aiida.work import run
    inputs = MPDSCrystalWorkchain.get_builder()
    inputs.crystal_code = test_crystal_code
    inputs.properties_code = test_properties_code
    inputs.crystal_parameters = crystal_calc_parameters
    inputs.properties_parameters = properties_calc_parameters
    inputs.basis_family = DataFactory('str')('sto-3g')
    inputs.mpds_phase_id = DataFactory('int')(2320)   # MgO 225
    inputs.options = DataFactory('parameter')(dict={
        'resources': {
            'num_machines': 1,
            'num_mpiprocs_per_machine': 1
        }
    })
    results = run(MPDSCrystalWorkchain, **inputs)
    assert 'output_parameters' in results
    assert 'frequency_parameters' in results
    assert 'elastic_parameters' in results
    assert 'output_dos' in results
    assert 'output_bands' in results
