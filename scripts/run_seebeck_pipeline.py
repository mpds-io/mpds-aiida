#!/usr/bin/env python3

import sys
from aiida import load_profile
from aiida.plugins import DataFactory
from aiida.orm import Code
from aiida.engine import submit
from mpds_aiida.workflows.crystal_seebeck import MPDSCrystalSeebeckWorkChain

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

PROPERTIES_PARAMETERS = {
    'newk': {'k_points': [48, 48], 'fermi': True},
    'boltztra': {
        'trange': [300, 600, 300],
        'murange': [-0.5, 0.5, 0.05],
        'tdfrange': [-0.5, 0.5, 0.05],
        'relaxtim': 10,
    },
}

PROPERTIES_OPTIONS = {
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 1,
    },
    # dummy value, not used by yascheduler
    'max_wallclock_seconds': 42,
}

inputs = {
    'workchain_options': DataFactory('dict')(dict=workchain_options),
    'mpds_query': DataFactory('dict')(dict={'formulae': formula, 'sgs': sgs}),
    'properties_code': properties_code,
    'properties_parameters': DataFactory('dict')(dict=PROPERTIES_PARAMETERS),
    'properties_options': DataFactory('dict')(dict=PROPERTIES_OPTIONS),
    'metadata': {'label': f"{formula}/{sgs} seebeck pipeline"},
}

wc = submit(MPDSCrystalSeebeckWorkChain, **inputs)
print(f"Submitted MPDSCrystalSeebeckWorkChain for {formula}/{sgs} → PK={wc.pk}")
