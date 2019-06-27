#!/usr/bin/env python

""" A mock CRYSTAL executable for running MPDS tests
"""

import os
import shutil
from hashlib import md5
from mpds_aiida_workflows.tests import TEST_DIR

inputs = {'1c7aa9741156b9e55bb317772077bf0b': {'fort.34': '6b1423d9ecd3ba3c7395f2079555578c'},
          '69ef9865d836e0b3f4d38e87b41fe7c7': {'fort.34': '5537457e809147c474428dc2bcc32c5f'},
          '58a65239e738d951fe76d4b76247f127': {'fort.34': '5537457e809147c474428dc2bcc32c5f'},
          '8731c858bbe210cb21d1dff45eb9353b': {'fort.9': '909760912d24b5273f2eeea030f12a8c'}}
outputs = {'1c7aa9741156b9e55bb317772077bf0b': 'optimise',
           '69ef9865d836e0b3f4d38e87b41fe7c7': 'elastic',
           '58a65239e738d951fe76d4b76247f127': 'frequency',
           '8731c858bbe210cb21d1dff45eb9353b': 'properties'
           }


def checksum(file_name, cs=md5):
    with open(file_name, 'rb') as f:
        data = f.read()
    return cs(data).hexdigest()


def main():
    cwd = os.getcwd()
    files = os.listdir(cwd)
    input_files = ('INPUT', 'main.d12', 'main.d3')
    assert any([f in files for f in input_files])
    cs = checksum('INPUT' if 'INPUT' in files else 'main.d3')
    assert cs in inputs
    for k, v in inputs[cs].items():
        assert k in files and checksum(k) == v
    out_dir = os.path.join(TEST_DIR, 'output_files', outputs[cs])
    for f in os.listdir(out_dir):
        shutil.copy(os.path.join(out_dir, f), cwd)


if __name__ == "__main__":
    main()
