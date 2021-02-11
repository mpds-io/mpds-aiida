#!/usr/bin/env python3

import os, sys
import json
#from pprint import pprint

import numpy as np
import matplotlib.pyplot as plt

from aiida import load_profile
from aiida_crystal_dft.io.f9 import Fort9
from mpds_aiida.common import get_template
from mpds_aiida.properties import properties_run_direct, properties_export


load_profile()
calc_setup = get_template('production.yml')

folder = '/tmp/_props'
if os.path.exists(folder):
    assert not os.listdir(folder), "Folder %s must be empty" % folder
else:
    os.makedirs(folder)

output, _, error = properties_run_direct(sys.argv[1], calc_setup['parameters']['properties'], folder)
if error:
    raise RuntimeError(error)

bands, dos = output

print("Writing JSONs")

wf = Fort9(sys.argv[1])
result, error = properties_export(bands, dos, wf.get_ase())
if error:
    raise RuntimeError(error)

f = open('bands.json', 'w')
f.write(json.dumps({'sample': {'measurement': [{'property': {'matrix': {
    'bands': result['stripes'],
    'kpoints': result['k_points']
}}}]}, 'use_visavis_type': 'eigenplot'}))
f.close()

f = open('dos.json', 'w')
f.write(json.dumps({'sample': {'measurement': [{'property': {'matrix': {
    'dos': result['dos'],
    'levels': result['levels']
}}}]}, 'use_visavis_type': 'eigenplot'}))
f.close()

print("Writing e_props.png")

f, (ax0, ax1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(10, 8))
x = np.arange(bands.get_array('kpoints').shape[0])
ax0.set_xlim(0, len(x)-1)
ax0.set_ylim(-10, 20)

ax0.set_xticks(bands.attributes['label_numbers'])
ax0.set_xticklabels(bands.attributes['labels'])
ax0.plot(x, bands.get_array('bands'), 'b')
ax1.set_xlim(0, 2000)
ax1.set_ylim(-10, 20)
ax1.plot(dos['dos_up'].T, (dos['e'] - dos['e_fermi']))

plt.savefig('e_props.png', dpi=250)

print('E_dir, E_ind = ', result['direct_gap'], result['indirect_gap'])