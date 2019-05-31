"""
A sample script running MPDS Aiida workflow
"""

""" This is a test of base workchain submission for CRYSTAL calculation
"""
import yaml

from aiida.orm import DataFactory, Code
from aiida.work import submit
from mpds_aiida_workflows.crystal import MPDSCrystalWorkchain
from .helper import get_phases


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

