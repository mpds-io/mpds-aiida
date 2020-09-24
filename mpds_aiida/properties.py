"""
This is the module to quickly (re-)run the CRYSTAL properties
locally at the AiiDA master, however outside of the AiiDA graph
NB
ln -s /root/bin/Pproperties /usr/bin/Pproperties
apt-get -y install openmpi-bin
"""
import os
import time
import random
import shutil
import subprocess
from configparser import ConfigParser
import warnings
import string
from datetime import datetime

import numpy as np
from ase.units import Hartree
from yascheduler import CONFIG_FILE
from aiida.plugins import DataFactory
from aiida_crystal_dft.io.f9 import Fort9
from aiida_crystal_dft.io.d3 import D3
from aiida_crystal_dft.io.f25 import Fort25
from aiida_crystal_dft.io.f34 import Fort34
from aiida_crystal_dft.utils.kpoints import construct_kpoints_path, get_explicit_kpoints_path, get_shrink_kpoints_path
import psutil


EXEC_PATH = "/usr/bin/Pproperties"
#EXEC_PATH = "/root/bin/properties" # NB. MAY BE NEEDED AT SOME AIIDA INSTANCES, E.G. AT SCW
EXEC_TIMEOUT = 900 # NB fifteen minutes
exec_cmd = "/usr/bin/mpirun -np 1 --allow-run-as-root -wd %s %s > %s 2>&1"
#exec_cmd = "cd %s && %s < INPUT > %s 2>&1" # NB. MAY BE NEEDED AT SOME AIIDA INSTANCES, E.G. AT SCW

config = ConfigParser()
config.read(CONFIG_FILE)

f34_input = Fort34()


def is_conductor(band_stripes):
    for s in band_stripes:
        top, bottom = max(s), min(s)
        if bottom < 0 and top > 0: return True
        elif bottom > 0: break
    return False


def get_band_gap_info(band_stripes):
    """
    Args:
        band_stripes: (2d-array) spaghetti in eV
    Returns:
        (tuple) indirect_gap, direct_gap
    """
    for n in range(1, len(band_stripes)):
        bottom = np.min(band_stripes[n])
        if bottom > 0:
            top = np.max(band_stripes[n - 1])
            if top < bottom:
                direct_gap = np.min(band_stripes[n] - band_stripes[n - 1])
                indirect_gap = bottom - top
                break
            else:
                return None, None
    else:
        raise RuntimeError("Unexpected data in band structure: no bands above zero found!")

    if direct_gap <= indirect_gap:
        return False, direct_gap
    else:
        return indirect_gap, direct_gap


def guess_metal(ase_obj):
    """
    Make an educated guess of the metallic compound character,
    returns bool
    """
    non_metallic_atoms = {
    'H',                                  'He',
    'Be',   'B',  'C',  'N',  'O',  'F',  'Ne',
                  'Si', 'P',  'S',  'Cl', 'Ar',
                  'Ge', 'As', 'Se', 'Br', 'Kr',
                        'Sb', 'Te', 'I',  'Xe',
                              'Po', 'At', 'Rn',
                                          'Og'
    }
    return not any([el for el in set(ase_obj.get_chemical_symbols()) if el in non_metallic_atoms])


def kill(proc_pid):
    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
        proc.kill()
    process.kill()


def get_avg_charges(ase_obj):
    at_type_chgs = {}
    for atom in ase_obj:
        at_type_chgs.setdefault(atom.symbol, []).append(atom.charge)

    if sum([sum(at_type_chgs[at_type]) for at_type in at_type_chgs]) == 0.0:
        return None

    return {at_type: np.average(at_type_chgs[at_type]) for at_type in at_type_chgs}


def properties_run_direct(wf_path, input_dict, work_folder=None):
    """
    This procedure runs properties
    outside of the AiiDA graph and scheduler,
    returns (bands, dos), work_folder, error
    """
    assert wf_path.endswith('fort.9') and 'band' in input_dict and 'dos' in input_dict
    assert 'first' not in input_dict['dos'] and 'first' not in input_dict['band']
    assert 'last' not in input_dict['dos'] and 'last' not in input_dict['band']

    if not work_folder:
        work_folder = os.path.join(config.get('local', 'data_dir'), '_'.join([
            'props',
            datetime.now().strftime('%Y%m%d_%H%M%S'),
            ''.join([random.choice(string.ascii_lowercase) for _ in range(4)])
        ]))
        os.makedirs(work_folder, exist_ok=False)

    shutil.copy(wf_path, work_folder)
    shutil.copy(os.path.join(os.path.dirname(wf_path), 'fort.34'), work_folder) # save structure

    wf = Fort9(os.path.join(work_folder, 'fort.9'))
    # automatic generation of k-point path
    #structure = wf.get_structure()
    last_state = wf.get_ao_number()
    # NB fort.9 may produce slightly different structure, so use fort.34

    f34 = f34_input.read(os.path.join(os.path.dirname(wf_path), 'fort.34'))
    structure = f34.to_aiida()

    shrink, _, kpath = get_shrink_kpoints_path(structure)
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
        return None, work_folder, 'PROPERTIES killed as too time-consuming'

    print("Done in %1.2f sc" % (time.time() - start_time))

    if p.returncode != 0:
        return None, work_folder, 'PROPERTIES failed'

    if not os.path.exists(os.path.join(work_folder, 'BAND.DAT')) \
        or not os.path.exists(os.path.join(work_folder, 'DOSS.DAT')) \
        or not os.path.exists(os.path.join(work_folder, 'fort.25')):
        return None, work_folder, 'PROPERTIES missing outputs'

    result = Fort25(os.path.join(work_folder, 'fort.25')).parse()
    bands = result.get("BAND", None)
    dos = result.get("DOSS", None)
    if not bands or not dos:
        return None, work_folder, 'PROPERTIES missing BANDS or DOS'

    # get rid of the negative DOS artifacts
    dos['dos_up'][ dos['dos_up'] < 0 ] = 0
    dos['dos_up'] *= Hartree
    if dos['dos_down'] is not None:
        assert len(dos['dos_up'][0]) == len(dos['dos_down'][0])
        dos['dos_down'][ dos['dos_down'] < 0 ] = 0
        dos['dos_down'] *= Hartree
        # sum up and down: FIXME
        dos['dos_up'] += dos['dos_down']

    dos['e'] *= Hartree
    dos['e_fermi'] *= Hartree

    #cell = wf.get_cell(scale=True) # for path construction we're getting geometry from fort.9
    # NB fort.9 may produce slightly different structure, so use fort.34
    cell = f34.abc, f34.positions, f34.atomic_numbers

    path_description = construct_kpoints_path(cell, bands['path'], shrink, bands['n_k'])
    # find k-points along the path
    k_points = get_explicit_kpoints_path(structure, path_description)['explicit_kpoints']

    # pass through the internal AiiDA repr
    bands_data = DataFactory('array.bands')()
    bands_data.set_kpointsdata(k_points)
    if bands['bands_down'] is not None:
        # sum up and down: FIXME
        bands_data.set_bands(np.hstack(( (bands['bands_up'] - bands['e_fermi']) * Hartree, (bands['bands_down'] - bands['e_fermi']) * Hartree )))
    else:
        bands_data.set_bands((bands['bands_up'] - bands['e_fermi']) * Hartree)

    return (bands_data, dos), work_folder, None


def properties_export(bands_data, dos_data, ase_struct):

    bands_array = bands_data.get_array('bands')
    e_min, e_max = np.amin(bands_array), np.amax(bands_array)
    dos_energies = np.linspace(e_min, e_max, num=len(dos_data['dos_up'][0]))
    stripes = bands_array.transpose().copy()

    if is_conductor(stripes):
        indirect_gap, direct_gap = None, None
    else:
        indirect_gap, direct_gap = get_band_gap_info(stripes)

    if direct_gap > 50 or indirect_gap > 50:
        return None, '%s: UNPHYSICAL BAND GAP: %s / %s' % (ase_struct.get_chemical_formula(), direct_gap, indirect_gap)

    if direct_gap > 15 or indirect_gap > 15:
        warnings.warn('%s: SUSPICION FOR UNPHYSICAL BAND GAP: %s / %s' % (ase_struct.get_chemical_formula(), direct_gap, indirect_gap))

    if guess_metal(ase_struct) and (direct_gap or indirect_gap):
        warnings.warn('%s: SUSPICION FOR METAL WITH BAND GAPS: %s / %s' % (ase_struct.get_chemical_formula(), direct_gap, indirect_gap))

    # export only the range of the interest
    E_MIN, E_MAX = -10, 20
    stripes = stripes[ (stripes[:,0] > E_MIN) & (stripes[:,0] < E_MAX) ]
    dos = []
    for n, ene in enumerate(dos_energies): # FIXME use numpy advanced slicing
        if E_MIN < ene < E_MAX:
            dos.append(dos_data['dos_up'][0][n])
    dos_energies = dos_energies[ (dos_energies > E_MIN) & (dos_energies < E_MAX) ]

    return {
        # gaps
        'direct_gap': direct_gap,
        'indirect_gap': indirect_gap,

        # dos values
        'dos': np.round(np.array(dos), 3).tolist(),
        'levels': np.round(dos_energies, 3).tolist(),

        # bands values
        'k_points': bands_data.get_array('kpoints').tolist(),
        'stripes': np.round(stripes, 3).tolist(),
    }, None
