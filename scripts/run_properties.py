#!/usr/bin/env python3

import sys
import json
#from pprint import pprint

from mpds_aiida.common import get_template
from mpds_aiida.properties import run_properties_direct
from aiida import load_profile

load_profile()
calc_setup = get_template('production.yml')

result, error = run_properties_direct(sys.argv[1], calc_setup['parameters']['properties'])
if error:
    raise RuntimeError(error)

#print(result)
print("Writing JSONs")

bands = {'bands': result['stripes'], 'kpoints': result['k_points']}
dos = {'dos': result['dos'], 'levels': result['levels']}

f = open('bands.json', 'w')
f.write(json.dumps({'sample': {'measurement': [{'property': {'matrix': bands}}]}, 'use_visavis_type': 'eigenplot'}))
f.close()

f = open('dos.json', 'w')
f.write(json.dumps({'sample': {'measurement': [{'property': {'matrix': dos}}]}, 'use_visavis_type': 'eigenplot'}))
f.close()