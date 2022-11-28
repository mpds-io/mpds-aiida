#!/usr/bin/env python3

import sys

from aiida import load_profile
from aiida.plugins import DataFactory
from aiida.engine import submit
from mpds_aiida.workflows.aiida import AiidaStructureWorkChain

import spglib

from mpds_ml_labs.struct_utils import detect_format, refine, get_formula
from mpds_ml_labs.cif_utils import cif_to_ase


load_profile()

structure = open(sys.argv[1]).read()
assert detect_format(structure) == 'cif'
ase_obj, error = cif_to_ase(structure)
assert not error, error
assert 'disordered' not in ase_obj.info

try: symprec = float(sys.argv[2])
except: symprec = 3E-02 # NB needs tuning
print('symprec = %s' % symprec)

label = get_formula(ase_obj) + "/" + spglib.get_spacegroup(ase_obj, symprec=symprec)

ase_obj, error = refine(ase_obj, accuracy=symprec, conventional_cell=True)
assert not error, error

inputs = AiidaStructureWorkChain.get_builder()
inputs.metadata = dict(label=label)
inputs.structure = DataFactory('structure')(ase=ase_obj)

wc = submit(AiidaStructureWorkChain, **inputs)
print("Submitted WorkChain %s" % wc.pk)
