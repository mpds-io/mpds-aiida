#!/usr/bin/env python3

from itertools import product

from aiida import load_profile
from aiida.plugins import DataFactory
from aiida.orm import Code
from aiida.engine import submit
from mpds_aiida.workflows.crystal import MPDSCrystalWorkchain

from mpds_client import MPDSDataRetrieval
from mpds_aiida.common import get_template, get_mpds_phases


ela = ['Li', 'Na', 'K', 'Rb', 'Be', 'Mg', 'Ca', 'Sr']
elb = ['F', 'Cl', 'Br', 'I', 'O', 'S', 'Se', 'Te']

client = MPDSDataRetrieval()

calc_setup = get_template()

load_profile()

inputs = MPDSCrystalWorkchain.get_builder()
inputs.crystal_code = Code.get_from_string('{}@{}'.format(calc_setup['codes'][0], calc_setup['cluster']))
inputs.crystal_parameters = DataFactory('dict')(dict=calc_setup['parameters']['crystal'])

inputs.basis_family, _ = DataFactory('crystal.basis_family').get_or_create(calc_setup['basis_family'])
inputs.options = DataFactory('dict')(dict=calc_setup['options'])

for elem_pair in product(ela, elb):
    print(elem_pair)
    phases = get_mpds_phases(client, elem_pair, more_query_args=dict(lattices='cubic'))

    for phase in phases:
        formula, sgs, pearson = phase.split('/')
        inputs.metadata = {'label': phase}
        inputs.mpds_query = DataFactory('dict')(dict={'formulae': formula, 'sgs': int(sgs)})
        wc = submit(MPDSCrystalWorkchain, **inputs)
        print("Submitted WorkChain %s for %s" % (wc.pk, phase))
