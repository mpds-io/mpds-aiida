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

from yascheduler import CONFIG_FILE
from aiida_crystal.io.f9 import Fort9
from aiida_crystal.io.d3 import D3
from aiida_crystal.utils.kpoints import get_shrink_kpoints_path


EXEC_PATH = "/usr/bin/Pproperties"
exec_cmd = "/usr/bin/mpirun -np 1 --allow-run-as-root -wd %s %s > %s 2>&1"

config = ConfigParser()
config.read(CONFIG_FILE)


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
    _, err = p.communicate()
    print("Done in %1.2f sc" % (time.time() - start_time))

    if p.returncode != 0:
        return None, 'PROPERTIES failed: %s' % err

    if not os.path.exists(os.path.join(work_folder, 'BAND.DAT')) \
        or not os.path.exists(os.path.join(work_folder, 'DOSS.DAT')) \
        or not os.path.exists(os.path.join(work_folder, 'fort.25')):
        return None, 'No PROPERTIES outputs'

    return work_folder, None