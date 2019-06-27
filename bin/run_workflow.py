"""
A sample script running MPDS Aiida workflow
"""
import os
import yaml
import pandas as pd
from itertools import product
from mpds_client import MPDSDataRetrieval

from aiida.orm import DataFactory, Code
from aiida.work import submit
from mpds_aiida_workflows.crystal import MPDSCrystalWorkchain


def get_formulae():
    el1 = ['Li', 'Na', 'K']
    el2 = ['F', 'Cl', 'Br']
    for pair in product(el1, el2):
        yield {'elements': '-'.join(pair), 'classes': 'binary'}


def get_phases():
    key = os.getenv('MPDS_KEY', None)
    if key is None:
        raise EnvironmentError('Environment variable MPDS_KEY not set, aborting')
    cols = ['phase_id', 'chemical_formula', 'sg_n']
    client = MPDSDataRetrieval(api_key=key)
    for formula in get_formulae():
        formula.update({'props': 'atomic structure'})
        data = client.get_data(formula, fields={'S': cols})
        data_df = pd.DataFrame(data=data, columns=cols).dropna(axis=0, how="all", subset=["phase_id"])
        phase_ids = data_df["phase_id"].unique()
        for phase in phase_ids:
            phase_data = data_df[data_df["phase_id"] == phase].iloc[0]
            yield {'formulae': phase_data['chemical_formula'],
                   'sgs': int(phase_data['sg_n'])}


with open('options.yml') as f:
    calc = yaml.load(f.read())

inputs = MPDSCrystalWorkchain.get_builder()
inputs.crystal_code = Code.get_from_string('{}@{}'.format(calc['codes'][0], calc['cluster']))
inputs.properties_code = Code.get_from_string('{}@{}'.format(calc['codes'][1], calc['cluster']))

inputs.crystal_parameters = DataFactory('parameter')(dict=calc['parameters']['crystal'])
inputs.properties_parameters = DataFactory('parameter')(dict=calc['parameters']['properties'])

inputs.basis_family = DataFactory('str')(calc['basis_family'])
# inputs.mpds_query = DataFactory('parameter')(dict=calc['structure'])

inputs.options = DataFactory('parameter')(dict=calc['options'])

for phase in get_phases():
    inputs.mpds_query = DataFactory('parameter')(dict=phase)
    inputs.label = '{formula} ({sg})'.format(formula=phase['formulae'], sg=phase['sgs'])
    wc = submit(MPDSCrystalWorkchain, **inputs)
    print("submitted WorkChain; PK = {}".format(wc.dbnode.pk))

