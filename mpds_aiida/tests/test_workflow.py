
import os
# noinspection PyUnresolvedReferences
from aiida.manage.tests.pytest_fixtures import temp_dir, aiida_localhost, aiida_profile, aiida_local_code_factory
from mpds_aiida.tests import TEST_DIR
# noinspection PyUnresolvedReferences
from mpds_aiida.tests.fixtures import test_basis


def test_workchain_run(aiida_localhost, aiida_profile, aiida_local_code_factory, test_basis):
    from mpds_aiida.workflows.mpds import MPDSStructureWorkChain
    from aiida.plugins import DataFactory
    from aiida.engine import run
    mock_exec = TEST_DIR / 'mock' / 'crystal'
    code = aiida_local_code_factory('mock_crystal', str(mock_exec))
    inputs = MPDSStructureWorkChain.get_builder()
    inputs.mpds_query = DataFactory('dict')(dict={
        "classes": "binary",
        "formulae": "MgO",
        "sgs": 225
    })   # MgO 225
    inputs.workchain_options = DataFactory('dict')(dict={
        'codes': {
            'crystal': code.full_label,
        },
        'basis_family': 'STO-3G'}
    )
    results = run(MPDSStructureWorkChain, **inputs)
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
