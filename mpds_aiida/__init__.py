# Copyright (c) Andrey Sobolev and Evgeny Blokhin, 2016-2019
# Distributed under MIT license, see LICENSE file.

import os
import glob
import shutil

__version__ = "0.8"

TEMPLATE_DIR = os.path.join(os.getenv('HOME'),
                            '.aiida',
                            'mpds_aiida')
os.makedirs(TEMPLATE_DIR, exist_ok=True)

yml_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "calc_templates"
)

for f in glob.glob(yml_dir + os.sep + '*.yml'):
    yml_file = os.path.basename(f)
    if not os.path.isfile(os.path.join(TEMPLATE_DIR, yml_file)):
        shutil.copy(yml_dir + os.sep + yml_file, TEMPLATE_DIR)
