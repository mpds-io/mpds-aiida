#!/usr/bin/env python3

import os
import sys

from aiida_crystal_dft.io.f34 import Fort34
from absolidix_backend.datasources.fmt import detect_format
from absolidix_backend.structures.struct_utils import refine
from absolidix_backend.structures.cif_utils import cif_to_ase

from yascheduler import Yascheduler

import spglib
from mpds_aiida.common import get_template, get_basis_sets, get_input


structure = open(sys.argv[1]).read()
assert detect_format(structure) == 'cif'
ase_obj, error = cif_to_ase(structure)
assert not error, error
assert 'disordered' not in ase_obj.info

try: symprec = float(sys.argv[2])
except: symprec = 3E-02 # NB needs tuning
print('symprec = %s' % symprec)

label = sys.argv[1].split(os.sep)[-1].split('.')[0] + \
    " " + spglib.get_spacegroup(ase_obj, symprec=symprec)

ase_obj, error = refine(ase_obj, accuracy=symprec, conventional_cell=True)
assert not error, error

yac = Yascheduler()

try: tpl = sys.argv[3]
except: tpl = 'minimal.yml'
print('Using template %s' % tpl)

calc_setup = get_template(tpl)
bs_repo = get_basis_sets(calc_setup['basis_family'])

#bs_repo_tzvp = get_basis_sets('./tzvp_RE')
#bs_repo_other = get_basis_sets('./hand_made_bs')
#bs_repo = {**bs_repo_tzvp , **bs_repo_other}

elements = list(set(ase_obj.get_chemical_symbols()))
f34_input = Fort34([bs_repo[el] for el in elements])
struct_input = str(f34_input.from_ase(ase_obj))
setup_input = str(get_input(calc_setup['default']['crystal'], elements, bs_repo, label))

result = yac.queue_submit_task(label, {"fort.34": struct_input, "INPUT": setup_input}, "pcrystal")
print(label)
print(result)
