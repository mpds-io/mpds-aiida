#!/home/andrey/miniconda3/envs/mpds-aiida/bin/python

""" A mock CRYSTAL executable for running MPDS tests
"""

import pathlib
import shutil
from hashlib import md5
from mpds_aiida.tests import TEST_DIR


def checksum(file_name, cs=md5):
    files = (file_name, 'fort.34')
    data = []
    for file_name in files:
        with open(file_name, 'rb') as f:
            data.append(b''.join(f.read().split()))
    return cs(b''.join(data)).hexdigest()[:8]


def main():
    cwd = pathlib.Path.cwd()
    files = [str(f.name) for f in cwd.glob('*')]
    input_files = ('INPUT', 'main.d12', 'main.d3')
    assert any([f in files for f in input_files])
    cs = checksum('INPUT' if 'INPUT' in files else 'main.d3')
    out_dir = pathlib.Path(TEST_DIR) / 'output_files'
    outputs = [str(f.name).split('.')[0] for f in out_dir.glob('*')]
    assert cs in outputs
    shutil.unpack_archive(out_dir / f'{cs}.tar.gz', cwd)


if __name__ == "__main__":
    main()
