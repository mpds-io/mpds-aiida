#  Copyright (c) Andrey Sobolev, 2019. Distributed under MIT license

"""
Functions concerning getting structures from MPDS
"""

import os
import pandas as pd
from itertools import product
from mpds_client import MPDSDataRetrieval


def get_formulae():
    el1 = ['Li', 'Na', 'K']
    el2 = ['F', 'Cl', 'Br']
    for pair in product(el1, el2):
        yield {'elements': '-'.join(pair), 'classes': 'binary'}


def get_phases():
    return {'formulae': 'MgO', 'sgs': 225}
    key = os.getenv('MPDS_KEY', None)
    if key is None:
        raise EnvironmentError('Environment variable MPDS_KEY not set, aborting')
    cols = ['phase_id', 'chemical_formula', 'sg_n']
    client = MPDSDataRetrieval(api_key=key)
    for formula in get_formulae():
        formula.update({'props': 'atomic structure'})
        data = client.get_data(formula, fields={'S': cols})
        data_df = pd.DataFrame(data=data, columns=cols).dropna(axis=0, how="all", subset=["phase_id"])
        phase_ids = data_df["phase_id"].unique()
        for phase in phase_ids:
            phase_data = data_df[data_df["phase_id"] == phase].iloc[0]
            yield {'formulae': phase_data['chemical_formula'],
                   'sgs': int(phase_data['sg_n'])}


if __name__ == "__main__":
    for phase in get_phases():
        print(phase)
