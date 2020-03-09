"""
ln -s /root/bin/Pproperties /usr/bin/Pproperties
"""
import os
import time
import random
import shutil
import subprocess
from configparser import ConfigParser
import string
from datetime import datetime

import numpy as np
from ase.units import Hartree
from yascheduler import CONFIG_FILE
from aiida.plugins import DataFactory
from aiida_crystal_dft.io.f9 import Fort9
from aiida_crystal_dft.io.d3 import D3
from aiida_crystal_dft.io.f25 import Fort25
from aiida_crystal_dft.utils.kpoints import construct_kpoints_path, get_explicit_kpoints_path, get_shrink_kpoints_path
import psutil


EXEC_PATH = "/usr/bin/Pproperties"
#EXEC_PATH = "/root/bin/properties"
EXEC_TIMEOUT = 300 # NB five minutes
exec_cmd = "/usr/bin/mpirun -np 1 --allow-run-as-root -wd %s %s > %s 2>&1"
#exec_cmd = "cd %s && %s < INPUT > %s 2>&1"

config = ConfigParser()
config.read(CONFIG_FILE)


def is_conductor(band_stripes):
    for s in band_stripes:
        top, bottom = max(s), min(s)
        if bottom < 0 and top > 0: return True
        elif bottom > 0: break
    return False


def get_bandgap(band_stripes, x_axis):
    # TODO if indirect gap found, find also direct one
    for n in range(1, len(band_stripes)):
        top, bottom = max(band_stripes[n]), min(band_stripes[n])
        if bottom > 0:
            lvb = max(band_stripes[n - 1])
            if lvb < bottom:
                homo_k = x_axis[ band_stripes[n - 1].index(lvb) ]
                lumo_k = x_axis[ band_stripes[n].index(bottom)]
                gap = bottom - lvb
                if gap > 50: # eV
                    raise RuntimeError("Unphysical band gap occured!")
                return gap, homo_k == lumo_k
            else:
                return 0.0, None

    raise RuntimeError("Unexpected data in band structure: no bands above zero found!")


def kill(proc_pid):
    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
        proc.kill()
    process.kill()


def run_properties_direct(wf_path, input_dict):
    """
    This procedure runs properties
    outside of AiiDA graph and scheduler
    """
    assert wf_path.endswith('fort.9')
    assert 'band' in input_dict and 'dos' in input_dict
    assert 'first' not in input_dict['dos'] and 'first' not in input_dict['band']
    assert 'last' not in input_dict['dos'] and 'last' not in input_dict['band']

    work_folder = os.path.join(config.get('local', 'data_dir'), '_'.join([
        'props',
        datetime.now().strftime('%Y%m%d_%H%M%S'),
        ''.join([random.choice(string.ascii_lowercase) for _ in range(4)])
    ]))
    os.makedirs(work_folder, exist_ok=False)
    shutil.copy(wf_path, work_folder)
    wf = Fort9(os.path.join(work_folder, 'fort.9'))

    # automatic generation of k-point path
    structure = wf.get_structure()
    shrink, _, kpath = get_shrink_kpoints_path(structure)
    last_state = wf.get_ao_number()
    input_dict['band']['shrink'] = shrink
    input_dict['band']['bands'] = kpath

    # automatic generation of first and last state
    input_dict['band']['first'] = 1
    input_dict['band']['last'] = last_state
    input_dict['dos']['first'] = 1
    input_dict['dos']['last'] = last_state

    d3_content = str(D3(input_dict))
    inp = open(os.path.join(work_folder, 'INPUT'), "w")
    inp.write(d3_content)
    inp.close()

    start_time = time.time()
    p = subprocess.Popen(
        exec_cmd % (work_folder, EXEC_PATH, os.path.join(work_folder, 'OUTPUT')),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
    )
    try:
        p.wait(timeout=EXEC_TIMEOUT)
    except subprocess.TimeoutExpired:
        kill(p.pid)
        print("Killed as too time-consuming")
    print("Done in %1.2f sc" % (time.time() - start_time))

    if p.returncode != 0:
        return None, 'PROPERTIES failed, see %s' % work_folder

    if not os.path.exists(os.path.join(work_folder, 'BAND.DAT')) \
        or not os.path.exists(os.path.join(work_folder, 'DOSS.DAT')) \
        or not os.path.exists(os.path.join(work_folder, 'fort.25')):
        return None, 'No PROPERTIES outputs'

    edata = Fort25(os.path.join(work_folder, 'fort.25')).parse()

    assert sum(edata['DOSS']['e']) == 0 # all zeros, FIXME?
    print('>N DOSS: %s' % len(edata['DOSS']['dos'][0]))

    path = edata['BAND']['path']
    k_number = edata['BAND']['n_k']
    cell = wf.get_cell(scale=True) # for path construction we're getting geometry from fort.9
    path_description = construct_kpoints_path(cell, path, shrink, k_number)
    # find k-points along the path
    k_points = get_explicit_kpoints_path(structure, path_description)['explicit_kpoints']

    # pass through the internal AiiDA repr, FIXME?
    bands_data = DataFactory('array.bands')()
    bands_data.set_kpointsdata(k_points)
    bands_data.set_bands(edata['BAND']['bands'])

    edata['BAND']['bands'] = bands_data.get_bands()
    k_points = bands_data.get_kpoints().tolist()
    print('>N KPOINTS: %s' % len(k_points))
    print('>N BANDS: %s' % len(edata['BAND']['bands'][0]))

    edata['BAND']['bands'] -= edata['DOSS']['e_fermi']
    edata['BAND']['bands'] *= Hartree
    e_min, e_max = np.amin(edata['BAND']['bands']), np.amax(edata['BAND']['bands'])
    dos_energies = np.linspace(e_min, e_max, num=len(edata['DOSS']['dos'][0]))
    stripes = edata['BAND']['bands'].transpose().copy().tolist()

    if is_conductor(stripes):
        gap, is_direct = None, None
    else:
        gap, is_direct = get_bandgap(stripes, k_points)

    return {
        'gap': gap,
        'is_direct': is_direct,
        'dos': edata['DOSS']['dos'].tolist(),
        'levels': dos_energies,
        'k_points': k_points,
        'stripes': stripes,
        'work_folder': work_folder,
        'units': 'eV'
    }, None
