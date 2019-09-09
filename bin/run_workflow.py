"""
A sample script running MPDS Aiida workflow
"""
import os
import yaml
import pandas as pd
from itertools import product
from mpds_client import MPDSDataRetrieval

from aiida.plugins import DataFactory
from aiida.orm import Code
from aiida.engine import submit
from mpds_aiida_workflows.crystal import MPDSCrystalWorkchain


def get_formulae():
    el1 = ['Li', 'Na', 'K', 'Rb', 'Cs']
    el2 = ['F', 'Cl', 'Br', 'I']
    # yield {'elements': 'Mg-O', 'classes': 'binary'}
    for pair in product(el1, el2):
        yield {'elements': '-'.join(pair), 'classes': 'binary'}


def get_phases():
    key = os.getenv('MPDS_KEY', None)
    if key is None:
        raise EnvironmentError('Environment variable MPDS_KEY not set, aborting')
    cols = ['phase', 'chemical_formula', 'sg_n']
    client = MPDSDataRetrieval(api_key=key)
    for formula in get_formulae():

        formula.update({'props': 'atomic structure'})
        data = client.get_data(formula, fields={'S': cols})
        data_df = pd.DataFrame(data=data, columns=cols).dropna(axis=0, how="all", subset=["phase"])
        for _, phase in data_df.drop_duplicates().iterrows():
            yield {'phase': phase['phase'],
                   'formulae': phase['chemical_formula'],
                   'sgs': int(phase['sg_n'])}


with open('options.yml') as f:
    calc = yaml.load(f.read())

inputs = MPDSCrystalWorkchain.get_builder()
inputs.crystal_code = Code.get_from_string('{}@{}'.format(calc['codes'][0], calc['cluster']))
inputs.properties_code = Code.get_from_string('{}@{}'.format(calc['codes'][1], calc['cluster']))

inputs.crystal_parameters = DataFactory('dict')(dict=calc['parameters']['crystal'])
inputs.properties_parameters = DataFactory('dict')(dict=calc['parameters']['properties'])

inputs.basis_family, _ = DataFactory('crystal.basis_family').get_or_create(calc['basis_family'])
# inputs.mpds_query = DataFactory('parameter')(dict=calc['structure'])

inputs.options = DataFactory('dict')(dict=calc['options'])

for phase in get_phases():
    inputs.label = phase.pop('phase')
    inputs.mpds_query = DataFactory('dict')(dict=phase)
    wc = submit(MPDSCrystalWorkchain, **inputs)
    print("submitted WorkChain; PK = {}".format(wc.dbnode.pk))

