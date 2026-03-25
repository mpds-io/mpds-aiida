# Copyright (c) Andrey Sobolev and Evgeny Blokhin, 2020-2026
# Distributed under MIT license, see LICENSE file.
# TODO fully support standard MPDS archives

import os
import sys
import shutil
from distutils import spawn
import subprocess
from enum import StrEnum, unique

import numpy as np

from aiida.orm import load_node
from aiida.orm import QueryBuilder, WorkChainNode, CalcJobNode
from aiida_crystal_dft.io.d12 import D12

from mpds_aiida.workflows.crystal import MPDSCrystalWorkChain


@unique
class CalcLabel(StrEnum):
    ELECTRON = 'ELECTRON'
    PHONON = 'PHONON'
    HFORM = 'HFORM'
    ELASTIC = 'ELASTIC'
    TRANSPORT = 'TRANSPORT'
    STRUCT = 'STRUCT'

OUTPUT_FILES = {
    'Geometry optimization': ['fort.34', 'fort.9'],
    'One-electron properties': ['fort.25']
}

EXEC = '7z' # can be 7zz on Mac
FOLDER = '/tmp/calc'
ARCHIVE_FILE = '/tmp/calc.7z'


def calculations_for_label(label):
    qb = QueryBuilder()
    qb.append(MPDSCrystalWorkChain, filters={'label': {'like': label}}, tag='root')
    qb.append(WorkChainNode, with_incoming='root', tag='parent')
    qb.append(CalcJobNode, with_incoming='parent', project=['label', 'uuid'])
    return {label: uuid for label, uuid in qb.iterall()}


def get_files(calc_label, uuid, folder):
    """
    TODO this should be refactored
    """
    calc = load_node(uuid)
    label = calc_label.split(':')[1].strip()
    repo_folder = calc.outputs.retrieved
    dst_folder = os.path.join(folder, label)
    if not os.path.isdir(dst_folder):
        os.makedirs(dst_folder)
    # input files
    input_dict = calc.inputs.parameters.get_dict()
    if 'properties' not in label:
        # CRYSTAL run
        basis_family = calc.inputs.basis_family
        basis_family.set_structure(calc.inputs.structure)
        input_d12 = D12(input_dict, basis_family)
        with open(os.path.join(dst_folder, 'INPUT'), 'w') as f:
            print(input_d12, file=f)
    else:
        # properties run
        from aiida_crystal_dft.io.d3 import D3
        d3 = D3(parameters=input_dict)
        with open(os.path.join(dst_folder, 'INPUT'), 'w') as f:
            d3.write(f)
    # stdout
    # TODO: What if the file name changes?
    with repo_folder.open('_scheduler-stderr.txt') as src:
        src_name = src.name
        dst_name = os.path.join(dst_folder, 'OUTPUT')
        shutil.copy(src_name, dst_name)
    # output files
    for file_name in OUTPUT_FILES.get(label, []):
        with repo_folder.open(file_name) as src:
            src_name = src.name
            dst_name = os.path.join(dst_folder, file_name)
            shutil.copy(src_name, dst_name)


def archive():
    """
    TODO this should be refactored
    """
    if spawn.find_executable(EXEC) is None:
        raise FileExistsError("7z archiver is not found on the system!")

    proc = subprocess.Popen([EXEC, "a", "-r", ARCHIVE_FILE, FOLDER],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    _, err = proc.communicate()
    if err:
        raise OSError("Error in archiving, details below\n{}".format(err))


def ase_to_optimade(ase_obj, name_id=None):
    result = dict(
        id=name_id or 'ase_to_optimade_export',
        attributes={},
        links=dict(self=None),
        type='structures'
    )
    result['attributes']['immutable_id'] = name_id or 'ase_to_optimade_export'
    result['attributes']['lattice_vectors'] = np.round(ase_obj.cell, 4).tolist()
    result['attributes']['cartesian_site_positions'] = []
    result['attributes']['species_at_sites'] = []
    for atom in ase_obj:
        result['attributes']['cartesian_site_positions'].append(np.round(atom.position, 4).tolist())
        result['attributes']['species_at_sites'].append(atom.symbol)
    return dict(data=[result])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: script.py label")
        sys.exit()

    calcs = calculations_for_label(sys.argv[1])
    for label, uuid in calcs.items():
        get_files(label, uuid, FOLDER)
    archive()
