
import os
import json
from collections import namedtuple

import yaml
from ase.data import chemical_symbols

from aiida_crystal_dft.io.d12 import D12
from aiida_crystal_dft.io.basis import BasisFile # NB only used to determine ecp
from mpds_client import APIError

from mpds_aiida import TEMPLATE_DIR


verbatim_basis = namedtuple("basis", field_names="content, all_electron")


def guess_metal(ase_obj):
    """
    Make an educated guess of the metallic compound character,
    returns bool
    """
    non_metallic_atoms = {
    'H',                                  'He',
    'Be',   'B',  'C',  'N',  'O',  'F',  'Ne',
                  'Si', 'P',  'S',  'Cl', 'Ar',
                  'Ge', 'As', 'Se', 'Br', 'Kr',
                        'Sb', 'Te', 'I',  'Xe',
                              'Po', 'At', 'Rn',
                                          'Og'
    }
    return not any([el for el in set(ase_obj.get_chemical_symbols()) if el in non_metallic_atoms])


def get_basis_sets(repo_dir):
    """
    Keeps all available BS in a dict for convenience
    NB. we assume BS repo_dir = AiiDA's *basis_family*
    """
    assert os.path.exists(repo_dir), "No folder %s with the basis sets found" % repo_dir
    bs_repo = {}
    for filename in os.listdir(repo_dir):
        if not filename.endswith('.basis'):
            continue

        el = filename.split('.')[0]
        assert el in chemical_symbols, "Unexpected basis set file %s" % filename
        with open(repo_dir + os.sep + filename, 'r') as f:
            bs_str = f.read().strip()

        bs_parsed = BasisFile().parse(bs_str)
        bs_repo[el] = verbatim_basis(content=bs_str, all_electron=('ecp' not in bs_parsed))

    return bs_repo


def get_template(template='minimal.yml'):
    """
    Templates present the permanent calc setup
    """
    template_loc = os.path.join(TEMPLATE_DIR, template)
    if not os.path.exists(template_loc):
        template_loc = template

    assert os.path.exists(template_loc)

    with open(template_loc) as f:
        calc = yaml.load(f.read(), Loader=yaml.SafeLoader)
    # assert 'parameters' in calc and 'crystal' in calc['parameters'] and 'basis_family' in calc
    return calc


def get_input(calc_params_crystal, elements, bs_src, label):
    """
    Generates a program input
    """
    calc_params_crystal['label'] = label

    if isinstance(bs_src, dict):
        return D12(parameters=calc_params_crystal, basis=[bs_src[el] for el in elements])

    elif isinstance(bs_src, str):
        return D12(parameters=calc_params_crystal, basis=bs_src)

    raise RuntimeError('Unknown basis set source format!')


supported_arities = {1: 'unary', 2: 'binary', 3: 'ternary', 4: 'quaternary', 5: 'quinary'}


def get_mpds_structures(mpds_api, elements, more_query_args=None):
    """
    Given some arbitrary chemical elements,
    get their possible crystalline structures

    Returns: list (NB dups)
    """
    assert sorted(list(set(elements))) == sorted(elements) and \
    len(elements) <= len(supported_arities)

    structures = []
    query = {
        "props": "atomic structure",
        "elements": '-'.join(elements),
        "classes": supported_arities[len(elements)] + ", non-disordered"
    }
    if more_query_args and type(more_query_args) == dict:
        query.update(more_query_args)

    try:
        for item in mpds_api.get_data(
            query,
            fields={'S': [
                'phase',
                'occs_noneq', # non-disordered phases may still have != 1
                'cell_abc',
                'sg_n',
                'basis_noneq',
                'els_noneq'
            ]}
        ):
            if item and any([occ != 1 for occ in item[1]]):
                continue

            ase_obj = mpds_api.compile_crystal(item, flavor='ase')
            if not ase_obj:
                continue

            ase_obj.info['phase'] = item[0]
            structures.append(ase_obj)

    except APIError as ex:
        if ex.code == 204:
            print("No results!")
            return []
        else: raise

    return structures


def get_mpds_phases(mpds_api, elements, more_query_args=None):
    """
    Given some arbitrary chemical elements,
    get their possible distinct phases,
    having at least one supported crystalline structure known

    Returns: set
    """
    assert sorted(list(set(elements))) == sorted(elements) and \
    len(elements) <= len(supported_arities)

    phases = set()
    query = {
        "props": "atomic structure",
        "elements": '-'.join(elements),
        "classes": supported_arities[len(elements)] + ", non-disordered"
    }
    if more_query_args and type(more_query_args) == dict:
        query.update(more_query_args)

    try:
        for item in mpds_api.get_data(
            query,
            fields={'S': [
                'phase',
                'occs_noneq', # non-disordered phases may still have != 1
                'els_noneq'
            ]}
        ):
            if not item or not item[-1]:
                continue

            if any([occ != 1 for occ in item[1]]):
                continue

            phases.add(item[0])

    except APIError as ex:
        if ex.code == 204:
            print("No results!")
            return []
        else: raise

    return phases


def get_aiida_cnf():
    cnf_path = os.path.expanduser('~/.aiida/config.json')
    assert os.path.exists(cnf_path)
    with open(cnf_path) as f:
        contents = json.loads(f.read())
    return contents['profiles'][contents['default_profile']]


def get_aiida_uuid(path_string):
    parts = path_string.split('/')
    for n in range(len(parts) - 1):
        if len(parts[n]) == 2 and len(parts[n + 1]) == 2:
            return parts[n] + parts[n + 1] + parts[n + 2]
    return False


def formula_to_latex(given_string):
    sub, output = False, ''
    for token in given_string:
        if token.isdigit() or token == '.':
            if not sub:
                output += '_{'
                sub = True
        else:
            if sub:
                output += '}'
                sub = False
        output += token
    if sub:
        output += '}'
    return '$' + output + '$'


def fix_label_names(labels):
    count = 1
    for n in range(len(labels)):
        if ',' in labels[n]:
            labels[n] = '$A_{%s}$' % count
            count += 1
    return labels


ARCHIVE_README = "\r\n".join("""In-house MPDS / PAULING FILE ab initio calculations data
(c) by Sobolev, Civalleri, Maschio, Erba, Dovesi, Villars, Blokhin

Please, cite as:
Sobolev, Civalleri, Maschio, Erba, Dovesi, Villars, Blokhin,
https://mpds.io/phase/{phase}
https://mpds.io/calculations/{aname}.7z

These data are licensed under a Creative Commons Attribution 4.0 International License.
http://creativecommons.org/licenses/by/4.0

The calculations are done using the CRYSTAL code:
Dovesi, Erba, Orlando, Zicovich-Wilson, Civalleri, Maschio, Rerat, Casassa,
Baima, Salustro, Kirtman. WIREs Comput Mol Sci. (2018),
https://doi.org/10.1002/wcms.1360
Dovesi, Saunders, Roetti, Orlando, Zicovich-Wilson, Pascale, Civalleri, Doll,
Harrison, Bush, D'Arco, Llunell, Causa, Noel, Maschio, Erba, Rerat, Casassa.
CRYSTAL17 User Manual (University of Turin, 2017), http://www.crystal.unito.it

The automation is done using the AiiDA code:
Pizzi, Cepellotti, Sabatini, Marzari, Kozinsky. Comp Mat Sci (2016),
https://doi.org/10.1016/j.commatsci.2015.09.013""".splitlines())
