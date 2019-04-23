#!/usr/bin/env python

""" A mock CRYSTAL executable for running MPDS tests
"""

import os
import shutil
from hashlib import md5
from mpds_aiida_workflows.tests import TEST_DIR

inputs = {'f5e32d03b2c5488de985d62edaf8a57e': {'fort.34': '6b1423d9ecd3ba3c7395f2079555578c'}}
outputs = {'f5e32d03b2c5488de985d62edaf8a57e': 'optimise'}


def checksum(file_name, cs=md5):
    with open(file_name, 'rb') as f:
        data = f.read()
    return cs(data).hexdigest()


def main():
    cwd = os.getcwd()
    files = os.listdir(cwd)
    assert 'INPUT' in files
    cs = checksum('INPUT')
    assert cs in inputs
    for k, v in inputs[cs].items():
        assert k in files and checksum(k) == v
    out_dir = os.path.join(TEST_DIR, 'output_files', outputs[cs])
    for f in os.listdir(out_dir):
        shutil.copy(os.path.join(out_dir, f), cwd)


if __name__ == "__main__":
    main()
