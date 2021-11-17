#!/usr/bin/env runaiida

import time
from aiida.manage.manager import get_manager
from aiida.cmdline.utils.query.calculation import CalculationQueryBuilder

builder = CalculationQueryBuilder()
filters = builder.get_filters(process_state=('created', 'waiting', 'running'))
query_set = builder.get_query_set(relationships={}, filters=filters)
projected = builder.get_projected(query_set, projections=CalculationQueryBuilder.default_projections)
headers = projected.pop(0)
procs = [(p[0], p[2]) for p in projected]

controller = get_manager().get_process_controller()
for label in (
              'CrystalParallelCalculation',
              'BaseCrystalWorkChain',
              'MPDSCrystalWorkchain'
             ):
    for pk, proc_label in procs:
        if label == proc_label:
            print(f'Restarting {pk}')
            controller.continue_process(pk, nowait=False, no_reply=True)
#            controller.kill_process(pk, msg=f'Killed {pk}')
            time.sleep(1)