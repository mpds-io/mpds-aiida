#  Copyright (c)  Andrey Sobolev, 2019. Distributed under MIT license, see LICENSE file.
""" Several utilities concerning getting input and output files from the repository
"""
from __future__ import print_function
import os
import shutil
import tarfile
import lzma
from aiida.orm import load_node
from aiida.orm import QueryBuilder, WorkChainNode, CalcJobNode
from aiida_crystal.io.d12_write import write_input
from mpds_aiida.workflows import GEOMETRY_LABEL, PROPERTIES_LABEL
from mpds_aiida.workflows.crystal import MPDSCrystalWorkchain


OUTPUT_FILES = {
    GEOMETRY_LABEL: ['fort.34', 'fort.9'],
    PROPERTIES_LABEL: ['fort.25']
}

FOLDER = '/tmp/calc'
ARCHIVE_FILE = '/tmp/calc.tar.xz'


def calculations_for_label(label):
    qb = QueryBuilder()
    qb.append(MPDSCrystalWorkchain, filters={'label': {'like': label}}, tag='root')
    qb.append(WorkChainNode, with_incoming='root', tag='parent')
    qb.append(CalcJobNode, with_incoming='parent', project=['label', 'uuid'])
    return {label: uuid for label, uuid in qb.iterall()}


def get_files(calc_label, uuid):
    calc = load_node(uuid)
    label = calc_label.split(':')[1].strip()
    repo_folder = calc.outputs.retrieved
    dst_folder = os.path.join(FOLDER, label)
    if not os.path.isdir(dst_folder):
        os.makedirs(dst_folder)
    # input files
    input_dict = calc.inputs.parameters.get_dict()
    if 'properties' not in label:
        # CRYSTAL run
        basis_family = calc.inputs.basis_family
        basis_family.set_structure(calc.inputs.structure)
        with open(os.path.join(dst_folder, 'INPUT'), 'w') as f:
            print(write_input(input_dict, basis_family), file=f)
    else:
        # properties run
        from aiida_crystal.io.d3 import D3
        d3 = D3(parameters=input_dict)
        with open(os.path.join(dst_folder, 'INPUT'), 'w') as f:
            d3.write(f)
    # stdout
    # TODO: What if the file name changes?
    with repo_folder.open('_scheduler-stderr.txt') as src:
        src_name = src.name
        dst_name = os.path.join(dst_folder, 'crystal.out')
        shutil.copy(src_name, dst_name)
    # output files
    for file_name in OUTPUT_FILES.get(label, []):
        with repo_folder.open(file_name) as src:
            src_name = src.name
        dst_name = os.path.join(dst_folder, file_name)
        shutil.copy(src_name, dst_name)


def archive(folder):
    xz_file = lzma.LZMAFile(ARCHIVE_FILE, mode='w')
    with tarfile.open(mode='w', fileobj=xz_file) as tar_xz_file:
        tar_xz_file.add(folder)
    xz_file.close()


if __name__ == "__main__":
    calcs = calculations_for_label("MgO/225")
    for label, uuid in calcs.items():
        get_files(label, uuid)
