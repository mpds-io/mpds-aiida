#!/usr/bin/env python3

import sys
import random
from itertools import product
from configparser import ConfigParser

import numpy as np
from aiida_crystal_dft.io.f34 import Fort34

from yascheduler import CONFIG_FILE
from yascheduler.scheduler import Yascheduler

from mpds_client import MPDSDataRetrieval
from mpds_aiida.common import get_template, get_basis_sets, get_mpds_structures, get_input


ela = ['Li', 'Na', 'K', 'Rb', 'Be', 'Mg', 'Ca', 'Sr']
elb = ['F', 'Cl', 'Br', 'I', 'O', 'S', 'Se', 'Te']

config = ConfigParser()
config.read(CONFIG_FILE)
yac = Yascheduler(config)

client = MPDSDataRetrieval()

calc_setup = get_template()
bs_repo = get_basis_sets(calc_setup['basis_family'])

try:
    how_many = int(sys.argv[1])
except (IndexError, ValueError):
    how_many = False

counter = 0
random.shuffle(ela)
random.shuffle(elb)

for elem_pair in product(ela, elb):
    if how_many and counter >= how_many: raise SystemExit

    print(elem_pair)
    structures = get_mpds_structures(client, elem_pair, more_query_args=dict(lattices='cubic'))
    structures_by_sgn = {}

    for s in structures:
        structures_by_sgn.setdefault(s.info['spacegroup'].no, []).append(s)

    for sgn_cls in structures_by_sgn:

        if how_many and counter >= how_many: raise SystemExit

        # get structures with the minimal number of atoms and find one with the median cell vectors
        minimal_struct = min([len(s) for s in structures_by_sgn[sgn_cls]])
        cells = np.array([s.get_cell().reshape(9) for s in structures_by_sgn[sgn_cls] if len(s) == minimal_struct])
        median_cell = np.median(cells, axis=0)
        median_idx = int(np.argmin(np.sum((cells - median_cell)**2, axis=1)**0.5))
        target_obj = structures_by_sgn[sgn_cls][median_idx]

        f34_input = Fort34([bs_repo[el] for el in elem_pair])
        struct_input = f34_input.from_ase(target_obj)
        setup_input = get_input(calc_setup['parameters']['crystal'], elem_pair, bs_repo, target_obj.info['phase'])
        struct_input = str(struct_input)
        setup_input = str(setup_input)

        yac.queue_submit_task(target_obj.info['phase'], dict(structure=struct_input, input=setup_input))
        counter += 1