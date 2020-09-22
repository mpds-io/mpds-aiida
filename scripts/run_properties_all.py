#!/usr/bin/env python3

import os, sys
import traceback
import time
import copy
from datetime import datetime
import socket

import pg8000
import ujson as json

from mpds_aiida.common import get_template, get_aiida_cnf
from mpds_aiida.properties import guess_metal, run_properties_direct
from tilde.core.api import API as TildeAPI
from aiida import load_profile


load_profile()
aiida_cnf = get_aiida_cnf()
calc_setup = get_template('production.yml')
calc_analysis = TildeAPI()
results = {}

pgconn = pg8000.connect(user=aiida_cnf['AIIDADB_USER'], password=aiida_cnf['AIIDADB_PASS'], database=aiida_cnf['AIIDADB_NAME'], host=aiida_cnf['AIIDADB_HOST'])
pgcursor = pgconn.cursor()

OUTPUT_FILE = 'eprops_%s_%s.json' % (socket.gethostname(), datetime.now().strftime('%Y%m%d'))

start_time = time.time()
pgcursor.execute("SELECT label, attributes->>'remote_workdir' FROM db_dbnode WHERE label LIKE '%Geometry optimization%' ORDER BY label;")
for row in pgcursor.fetchall():

    if not row[1] \
    or not os.path.exists(row[1]) \
    or not os.path.exists(row[1] + os.sep + 'fort.9') \
    or os.stat(row[1] + os.sep + 'fort.9').st_size == 0 \
    or (os.path.exists(row[1] + os.sep + 'fort.87') and os.stat(row[1] + os.sep + 'fort.87').st_size != 0):
        continue

    phase = row[0].split(': ')[0]

    for f in list(os.listdir(row[1])):
        calc, error = list(calc_analysis.parse(row[1] + os.sep + f))[0]
        if error:
            continue
        calc, error = calc_analysis.classify(calc)
        if error:
            continue
        if calc.info['framework'] == 0x3 and calc.info['finished'] == 0x2 and calc.info['H'] == 'PBE0':
            # production-only
            break
    else:
        continue

    try:
        result, error = run_properties_direct(row[1] + os.sep + 'fort.9', copy.deepcopy(calc_setup['parameters']['properties']))
    except: # handle internal errors
        exc_type, exc_value, exc_tb = sys.exc_info()
        error = "ERROR: Exception at %s: %s" % (phase, "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        result = {'error': error}
        print(error)
    if error:
        error = "ERROR: Properties failed at %s: %s" % (phase, error)
        result = {'error': error}
        print(error)

    if phase in results:
        print("%s and %s are dups" % (results[phase].get('work_folder'), result.get('work_folder', row[1])))
        continue

    if guess_metal(calc.structures[-1]) and (result.get('direct_gap') or result.get('indirect_gap')):
        print('CAUTION! %s: SUSPICION FOR METAL WITH BAND GAP' % phase)

    results[phase] = result

f = open(OUTPUT_FILE, 'w')
f.write(json.dumps(results))
f.close()
print("Done in %1.2f sc" % (time.time() - start_time))