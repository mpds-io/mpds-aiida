import argparse
import sys

import yaml
from aiida import load_profile
from aiida.engine import submit
from aiida.plugins import DataFactory
from mpds_aiida.workflows.mpds import MPDSStructureWorkChain


def main():
    load_profile()

    parser = argparse.ArgumentParser(description="Submit an MPDSStructureWorkChain job")
    parser.add_argument("phase",
                        nargs="?",
                        default="MgO/225",
                        help="Phase information in the format 'formula/sgs/pearson'")
    parser.add_argument("--scheme", default=None, help="Full path to the scheme file")
    args = parser.parse_args()

    phase = args.phase.split("/")

    if len(phase) == 3:
        formula, sgs, pearson = phase
    else:
        formula, sgs, pearson = phase[0], phase[1], None

    try:
        sgs = int(sgs)
    except ValueError:
        print(f"Error: space group should be an integer, got {sgs}")
        sys.exit(1)

    inputs = MPDSStructureWorkChain.get_builder()

    if args.scheme:
        try:
            with open(args.scheme) as f:
                inputs.workchain_options = yaml.safe_load(f)
        except FileNotFoundError:
            print(f"Error: Scheme file {args.scheme} not found")
            sys.exit(1)
        except yaml.YAMLError as exc:
            print(f"Error parsing YAML file: {exc}")
            sys.exit(1)
    else:
        inputs.workchain_options = {}

    inputs.metadata = {"label": "/".join(phase)}
    inputs.mpds_query = DataFactory('dict')(dict={'formulae': formula, 'sgs': sgs})
    calc = submit(MPDSStructureWorkChain, **inputs)
    print(f"Submitted WorkChain; calc=WorkCalculation(PK={calc.pk})")


if __name__ == "__main__":
    main()
