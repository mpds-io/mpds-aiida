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
    phase = ("MgO", "225")
    print("Default phase for testing: " + "/".join(phase))

if len(phase) == 3:
    formula, sgs, pearson = phase
else:
    formula, sgs, pearson = phase[0], phase[1], None

sgs = int(sgs)

inputs = MPDSStructureWorkChain.get_builder()

inputs.metadata = dict(label="/".join(phase))
inputs.mpds_query = DataFactory('dict')(dict={'formulae': formula, 'sgs': sgs})

wc = submit(MPDSStructureWorkChain, **inputs)
print("Submitted WorkChain %s" % wc.pk)