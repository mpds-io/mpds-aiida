#!/usr/bin/env python3

import sys
import os
import yaml
from aiida import load_profile
from aiida.plugins import DataFactory
from aiida.orm import Code
from aiida.engine import submit
from mpds_aiida.workflows.crystal_seebeck import MPDSCrystalSeebeckWorkChain

import os
load_profile()

try:
    phase = sys.argv[1].split("/")
except IndexError:
    phase = ("HCl", "225")
    print("Default phase for testing: " + "/".join(phase))

if len(phase) == 3:
    formula, sgs, pearson = phase
else:
    formula, sgs, pearson = phase[0], phase[1], None

sgs = int(sgs)

workchain_options_file = os.getenv("WORKCHAIN_OPTIONS", "nonmetallic.yml")
from mpds_aiida.common import get_template
workchain_options = get_template(workchain_options_file)

properties_code = Code.get_from_string(os.getenv("PROPERTIES_CODE", "pproperties@yascheduler"))

inputs = {
    'workchain_options': DataFactory('dict')(dict=workchain_options),
    'mpds_query': DataFactory('dict')(dict={'formulae': formula, 'sgs': sgs}),
    'properties_code': properties_code,
    'metadata': {'label': f"{formula}/{sgs} seebeck pipeline"},
}

wc = submit(MPDSCrystalSeebeckWorkChain, **inputs)
print(f"Submitted MPDSCrystalSeebeckWorkChain for {formula}/{sgs} → PK={wc.pk}")