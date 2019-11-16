#  Copyright (c) Andrey Sobolev, 2019. Distributed under MIT license
"""
Main click CLI commands
"""

import click
from mpds_aiida.utils import calculations_for_label, get_files, archive_folder
import tempfile


@click.option(["-p", "--phase"],
              help="MPDS phase for which to search DB")
@click.option(["-f", "--folder"],
              help="A temporary folder for storing calculation results")
@click.option(["-a", "--archive"],
              name="archive_file",
              help="File name of the archive")
def archive(phase, folder, archive_file):
    calcs = calculations_for_label(phase)
    for label, uuid in calcs.items():
        get_files(label, uuid, folder)
    archive_folder(archive_file)