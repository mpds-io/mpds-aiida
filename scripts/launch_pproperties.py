from aiida import load_profile
load_profile()
from aiida.orm import load_code, Dict
from mpds_aiida.workflows.properties import SeebeckPropertiesWorkChain
# from aiida.engine import submit
from aiida.engine import run


builder = SeebeckPropertiesWorkChain.get_builder()
builder.code = load_code("pproperties@yascheduler")
builder.crystal_calc_uuid = '1ef3408c-1702-49f0-b1dc-0c5832f2d323'
params = {
    'newk': {'k_points': [32, 32], 'fermi': True},
    'boltztra': {
        'trange': [300, 600, 300],
        'murange': [-10, 20, 0.05],
        'tdfrange': [-10, 20, 0.05],
        'relaxtim': 10
    }
}
builder.parameters = Dict(dict=params)

builder.options = Dict(dict={
    'resources': {
        'num_machines': 1,
        'num_mpiprocs_per_machine': 1
    },
    'max_wallclock_seconds': 3600,
})

run(builder)
# submit(builder)