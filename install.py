
import os
import glob
import shutil
from setuptools.command.build_py import build_py


class CustomBuild(build_py):
    def run(self):
        _setup_once()
        super().run()


def _setup_once():
    """
    Copy calc templates into ~/.aiida
    """
    print("Running one-time build step...")

    # Path ~/.aiida is expected
    TEMPLATE_DIR = os.path.join(os.getenv('HOME') or '/tmp', '.aiida', 'mpds_aiida')
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    tpl_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "calc_templates"
    )

    # TODO This code does not check for updates of the templates. Can cause issues if templates are updated.
    for item in glob.glob(tpl_dir + os.sep + '*.yml'):
        yml_file = os.path.basename(item)
        if not os.path.isfile(os.path.join(TEMPLATE_DIR, yml_file)):
            shutil.copy(tpl_dir + os.sep + yml_file, TEMPLATE_DIR)
