#!/usr/bin/env python3

import sys

from aiida import load_profile
from aiida.plugins import DataFactory
from aiida.orm import Code
from aiida.engine import submit
from mpds_aiida.workflows.aiida import AiidaStructureWorkChain
from mpds_aiida.common import get_template
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

try: tpl = sys.argv[2]
except: tpl = 'minimal.yml'
print('Using %s' % tpl)
calc_setup = get_template(tpl)
calc_setup['default']['crystal']['title'] = label

inputs = AiidaStructureWorkChain.get_builder()
###inputs.crystal_code = Code.get_from_string('{}@{}'.format(calc_setup['codes'][0], calc_setup['cluster']))
###inputs.crystal_parameters = DataFactory('dict')(dict=calc_setup['parameters']['crystal'])
###inputs.basis_family, _ = DataFactory('crystal_dft.basis_family').get_or_create(calc_setup['basis_family'])
###inputs.options = DataFactory('dict')(dict=calc_setup['options'])

inputs.metadata = dict(label=label)
inputs.structure = DataFactory('structure')(ase=ase_obj)
wc = submit(AiidaStructureWorkChain, **inputs)
print("Submitted WorkChain %s" % wc.pk)
