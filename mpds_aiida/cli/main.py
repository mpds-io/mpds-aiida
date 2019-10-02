#  Copyright (c) Andrey Sobolev, 2019. Distributed under MIT license
"""
Main click CLI commands
"""

import click
import tempfile


@click.option(["-p", "--phase"],
              help="MPDS phase for which to search DB")
@click.option(["-f", "--folder"],
              help="A temporary folder for storing calculation results")
@click.option(["-a", "--archive"],
              name="archive_file",
              help="File name of the archive")
def cli(phase, folder, archive_file):
    pass

