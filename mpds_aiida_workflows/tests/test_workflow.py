
# noinspection PyUnresolvedReferences
from mpds_aiida_workflows.tests.fixtures import *


def test_workchain_run(test_crystal_code,
                       crystal_calc_parameters,
                       test_properties_code,
                       properties_calc_parameters,
                       test_basis):
    from mpds_aiida_workflows.crystal import MPDSCrystalWorkchain
    from aiida.plugins import DataFactory
    from aiida.engine import run
    inputs = MPDSCrystalWorkchain.get_builder()
    inputs.crystal_code = test_crystal_code
    inputs.properties_code = test_properties_code
    inputs.crystal_parameters = crystal_calc_parameters
    inputs.properties_parameters = properties_calc_parameters
    inputs.basis_family, _ = DataFactory('crystal.basis_family').get_or_create('STO-3G')
    inputs.mpds_query = DataFactory('dict')(dict={
        "classes": "binary",
        "formulae": "MgO",
        "sgs": 225
    })   # MgO 225
    inputs.options = DataFactory('dict')(dict={
        'label': 'MgO/225/PS',
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


def test_mpds():
    from mpds_client import MPDSDataRetrieval
    key = os.getenv('MPDS_KEY')
    client = MPDSDataRetrieval(api_key=key)
    query_dict = dict(formulae="MgO", sgs=225, classes="binary")
    # insert props: atomic structure to query. Might check if it's already set to smth
    query_dict['props'] = 'atomic structure'
    answer = client.get_data(
        query_dict,
        fields={'S': [
            'phase',
        ]}
    )
    assert len(set(_[0] for _ in answer)) == 1
