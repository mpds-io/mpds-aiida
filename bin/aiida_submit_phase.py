#!/usr/bin/env python3

import os, sys
from aiida import load_profile
from aiida.plugins import DataFactory
from aiida.orm import Code
from aiida.engine import submit
from mpds_aiida.workflows.crystal import MPDSCrystalWorkchain
from mpds_aiida.common import get_template

load_profile()
calc_setup = get_template('production.yml')
phase = sys.argv[1].split("/")

if len(phase) == 3:
    formula, sgs, pearson = phase
else:
    formula, sgs, pearson = phase[0], phase[1], None

sgs = int(sgs)
calc_setup['parameters']['crystal']['title'] = "/".join(phase)

inputs = MPDSCrystalWorkchain.get_builder()
inputs.crystal_code = Code.get_from_string('{}@{}'.format(calc_setup['codes'][0], calc_setup['cluster']))
inputs.crystal_parameters = DataFactory('dict')(dict=calc_setup['parameters']['crystal'])
inputs.basis_family, _ = DataFactory('crystal.basis_family').get_or_create(calc_setup['basis_family'])
inputs.options = DataFactory('dict')(dict=calc_setup['options'])

inputs.metadata = dict(label="/".join(phase))
inputs.mpds_query = DataFactory('dict')(dict={'formulae': formula, 'sgs': sgs})
wc = submit(MPDSCrystalWorkchain, **inputs)
print("Submitted WorkChain %s" % wc.pk)