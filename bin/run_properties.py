#!/usr/bin/env python3

import sys
from pprint import pprint

from mpds_aiida.common import get_template
from mpds_aiida.properties import run_properties_direct
from aiida import load_profile

load_profile()
calc_setup = get_template('production.yml')

result, error = run_properties_direct(sys.argv[1], calc_setup['parameters']['properties'])
if error:
    raise RuntimeError(error)

pprint(result)