#  Copyright (c)  Andrey Sobolev, 2019. Distributed under MIT license, see LICENSE file.
""" Several utilities concerning getting input and output files from the repository
"""


def get_calculations_for_label(label):

    from aiida.orm import QueryBuilder
    from mpds_aiida.workflows.crystal import MPDSCrystalWorkchain
    qb = QueryBuilder()
    qb.append(MPDSCrystalWorkchain)
    for res in qb.all():
        print(res)


if __name__ == "__main__":
    get_calculations_for_label("MgO/227/cF8")
