#!/usr/bin/env python

""" A mock CRYSTAL executable for running MPDS tests
"""

import os
import shutil
from hashlib import md5
from mpds_aiida.tests import TEST_DIR

inputs = {'a97aea7204e8ada080e2be6c29344384': {'fort.34': '6b1423d9ecd3ba3c7395f2079555578c'},
          '226706c6adb6aaa7fd0b6338dc6cc92f': {'fort.34': '5537457e809147c474428dc2bcc32c5f'},
          '11c3f2ef8e7d603d5602142e464b692c': {'fort.34': '5537457e809147c474428dc2bcc32c5f'},
          '8731c858bbe210cb21d1dff45eb9353b': {'fort.9': '909760912d24b5273f2eeea030f12a8c'}}
outputs = {'a97aea7204e8ada080e2be6c29344384': 'optimise',
           '226706c6adb6aaa7fd0b6338dc6cc92f': 'elastic',
           '11c3f2ef8e7d603d5602142e464b692c': 'frequency',
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
