#!/usr/bin/env python3

import sys
from aiida import load_profile
from aiida.plugins import DataFactory
from aiida.engine import submit
from mpds_aiida.workflows.mpds import MPDSStructureWorkChain


load_profile()

try:
    phase = sys.argv[1].split("/")
except IndexError:
    print("TESTING! Default phase: MgO/225")
    phase = ["MgO", "225"]

if len(phase) == 3:
    formula, sgs, pearson = phase
else:
    formula, sgs, pearson = phase[0], phase[1], None

sgs = int(sgs)
calc_setup['default']['crystal']['title'] = "/".join(phase)

inputs = MPDSStructureWorkChain.get_builder()

inputs.metadata = dict(label="/".join(phase))
inputs.mpds_query = DataFactory('dict')(dict={'formulae': formula, 'sgs': sgs})

wc = submit(MPDSStructureWorkChain, **inputs)
print("Submitted WorkChain %s" % wc.pk)