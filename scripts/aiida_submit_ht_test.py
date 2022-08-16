#!/usr/bin/env python3

from itertools import product

from aiida import load_profile
from aiida.plugins import DataFactory
from aiida.orm import Code
from aiida.engine import submit
from mpds_aiida.workflows.crystal import MPDSCrystalWorkchain

from mpds_client import MPDSDataRetrieval
from mpds_aiida.common import get_template, get_mpds_phases


ela = ['Li', 'Na', 'K', 'Rb', 'Be', 'Mg']
elb = ['F', 'Cl', 'Br', 'I', 'O', 'S']

client = MPDSDataRetrieval()

calc_setup = get_template()

load_profile()

inputs = MPDSCrystalWorkchain.get_builder()

for elem_pair in product(ela, elb):
    print(elem_pair)
    phases = get_mpds_phases(client, elem_pair, more_query_args=dict(lattices='cubic'))

    for phase in phases:
        formula, sgs, pearson = phase.split('/')
        inputs.metadata = {'label': phase}
        inputs.mpds_query = DataFactory('dict')(dict={'formulae': formula, 'sgs': int(sgs)})
        wc = submit(MPDSCrystalWorkchain, **inputs)
        print("Submitted WorkChain %s for %s" % (wc.pk, phase))
