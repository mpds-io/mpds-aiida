#!/usr/bin/env python3

import os, sys
import traceback
import time
import copy
import pg8000
import ujson as json

from mpds_aiida.common import get_template, get_aiida_cnf
from mpds_aiida.properties import run_properties_direct
from tilde.core.api import API as TildeAPI
from aiida import load_profile


load_profile()
aiida_cnf = get_aiida_cnf()
calc_setup = get_template('production.yml')
calc_analysis = TildeAPI()
results = {}

pgconn = pg8000.connect(user=aiida_cnf['AIIDADB_USER'], password=aiida_cnf['AIIDADB_PASS'], database=aiida_cnf['AIIDADB_NAME'], host=aiida_cnf['AIIDADB_HOST'])
pgcursor = pgconn.cursor()

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
        print("--------- Exception at %s: %s" % (phase, "".join(traceback.format_exception(exc_type, exc_value, exc_tb))))
        continue
    if error:
        print("- Properties failed at %s: %s" % (phase, error))
        continue

    if phase in results:
        print("%s and %s are dups" % (results[phase]['work_folder'], result['work_folder']))
        continue

    results[phase] = result
    print(">>>>>>>> %s: E_ind.=%2.2f E_dir.=%2.2f" % (phase, result['indirect_gap'] or 0, result['direct_gap'] or 0))

f = open('e_props.json', 'w')
f.write(json.dumps(results))
f.close()
print("Done in %1.2f sc" % (time.time() - start_time))