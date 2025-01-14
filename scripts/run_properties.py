#!/usr/bin/env python3

import os, sys
from io import BytesIO
import json
#from pprint import pprint

import numpy as np
import matplotlib.pyplot as plt

from PIL import Image
from ase.data import chemical_symbols

from aiida import load_profile
from aiida_crystal_dft.io.f9 import Fort9
from aiida_crystal_dft.utils.dos import get_dos_projections_atoms

from mpds_aiida.common import get_template, fix_label_names, formula_to_latex
from mpds_aiida.properties import properties_run_direct, properties_export, dos_colors


load_profile()
calc_setup = get_template('nonmetallic.yml')

folder = '/tmp/_props'
if os.path.exists(folder):
    assert not os.listdir(folder), "Folder %s must be empty" % folder
else:
    os.makedirs(folder)

output, _, error = properties_run_direct(sys.argv[1], calc_setup['default']['properties'], folder)
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
bands.attributes['labels'] = fix_label_names(bands.attributes['labels'])

fig, (ax0, ax1) = plt.subplots(1, 2, gridspec_kw={'width_ratios': [3, 1]}, figsize=(10, 8))
x = np.arange(bands.get_array('kpoints').shape[0])
ax0.set_xlim(0, len(x) - 1)
ax0.set_ylim(-10, 20)
ax0.set_xticks(bands.attributes['label_numbers'])
ax0.set_xticklabels(bands.attributes['labels'], fontsize=5, rotation=90)
ax0.plot(x, bands.get_array('bands'), 'b')

ax1.set_xlim(0, 2000)
ax1.set_ylim(-10, 20)
ax1.set_prop_cycle(color=dos_colors)
ax1.plot(dos['dos_up'].T, (dos['e'] - dos['e_fermi']))

atsymbs = [chemical_symbols[x] for x in wf.get_atomic_numbers()]
count, padding = 0, 70
for proj in get_dos_projections_atoms(wf.get_atomic_numbers()):
    ax1.annotate(atsymbs[proj[0] - 1], xy=(count * padding, -150), xycoords='axes pixels', size=7, c=dos_colors[count])
    count += 1
ax1.annotate('Total', xy=(count * padding, -150), xycoords='axes pixels', size=7, c=dos_colors[count])

fig.suptitle(formula_to_latex(wf.get_ase().get_chemical_formula(empirical=True)))
plt.margins(0.2)
plt.subplots_adjust(bottom=0.15)
#plt.savefig('e_props.png', dpi=250)

mem = BytesIO()
plt.savefig(mem, format='png', dpi=250)
mem.seek(0)
im = Image.open(mem)
im2 = im.convert('RGB').convert('P', palette=Image.ADAPTIVE)
im2.save('e_props.png')

print('E_dir, E_ind = ', result['direct_gap'], result['indirect_gap'])