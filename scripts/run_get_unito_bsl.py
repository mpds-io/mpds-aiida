"""
This script parses and downloads the CRYSTAL online
basis set library and for each chemical element
selects and saves a single appropriate basis set
"""
import os
import pickle

from ase.data import chemical_symbols
from pycrystal import download_basis_library

from aiida_crystal_dft.io.basis import BasisFile
from pyparsing import ParseException


CACHE_FILE = 'bs_library.pkl'
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'rb') as f:
        bs_library = pickle.load(f)
else:
    bs_library = download_basis_library()
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(bs_library, f, protocol=2)

FOLDER = 'MPDSBSL_NEUTRAL'
assert not os.path.exists(FOLDER)
os.makedirs(FOLDER)

saved = set()

def save(el, content, neutralize_charge=False):
    assert not os.path.exists('%s/%s.basis' % (FOLDER, el))

    if neutralize_charge:
        try:
            bs = BasisFile().parse(content)
        except ParseException:
            raise RuntimeError('Format issue')
        if not bs.get('ecp') or bs['ecp'][0] != 'INPUT':
            raise RuntimeError('Format issue: must have ECP')

        bs = bs_to_neutral(bs)
        assert bs_get_charge(bs) == 0, bs_to_str(bs)

        content = bs_to_str(bs)

    with open('%s/%s.basis' % (FOLDER, el), 'w') as f:
        f.write(content + "\n")
    saved.add(el)


def bs_to_str(basis):
    out = ["{} {}".format(*basis['header']), ]
    if 'ecp' in basis:
        out.append(basis['ecp'][0])
        # INPUT ecp goes here
        if len(basis['ecp']) > 1:
            out.append('{} {} {} {} {} {} {}'.format(*basis['ecp'][1]))
            out += ['{} {} {}'.format(*x) for x in basis['ecp'][2]]
    for shell in basis['bs']:
        out.append('{} {} {} {} {}'.format(*shell[0]))
        if len(shell) > 1:
            # either 2 or 3 numbers represent each exponent
            exp = "   ".join(["{:.12f}"]*len(shell[1]))
            out += [exp.format(*x) for x in shell[1:]]
    return '\n'.join(out)


def bs_get_charge(basis):
    ecp_eff_charge = basis['ecp'][1][0]
    shell_charge = 0
    for shell in basis['bs']:
        orb_charge = shell[0][3]
        shell_charge += orb_charge
    return ecp_eff_charge - shell_charge


def bs_to_neutral(basis):
    diff = bs_get_charge(basis)
    if diff == 0:
        return basis

    assert diff > 0 and diff <= 3 # NB-1

    for n, shell in enumerate(basis['bs']):
        if shell[0][0] == 0 and shell[0][1] == 1 and shell[0][3] < 5.0: # NB-1
            basis['bs'][n][0][3] += diff
            break
    return basis


for el in sorted(bs_library.keys()):
    eidx = chemical_symbols.index(el)

    if len(bs_library[el]) == 1:
        save(el, bs_library[el][0]['data'])
        continue

    if 56 < eidx < 72 or 88 < eidx < 104: # f-elements
        for gbasis in bs_library[el]:
            title = gbasis['title'].lower()
            if 'no_g' in title:
                save(el, gbasis['data'], neutralize_charge=True)
        continue

    candidates = {}
    for gbasis in bs_library[el]:
        title = gbasis['title'].lower()
        if 'tzvp' in title:
            candidates[title] = gbasis['data']

    if len(candidates) == 1:
        save(el, list(candidates.values())[0])
        continue

    for title in candidates:
        if 'rev2' in title:
            save(el, candidates[title])

opinionated_choice = {
    'Bi': 'Bi_ECP60MFD_s4411p411d411_Heifets_2013',
    #'Ba': 'Ba_HAYWSC-31(2df)G_mahmoud_2013',
    #'Pb': 'Pb_ECP60MDF_doll_2011',
    'Au': 'Au_weihrich_2006',
    #'Cs': 'Cs_SC_HAYWSC-31(1d)G_baranek_2013_CsTaO3',
    'Tl': 'Tl_HAYWLC-3131d31G_Bachhuber_2011',
    #'Ta': 'Ta_ECP60MDF-31(51df)G_baranek_2013_KTaO3',
    'Pt': 'Pt_doll_2004'
}

unsaved = set(bs_library.keys()) - saved
for el in unsaved:
    print(el, [item['title'] for item in bs_library[el]])
    for item in bs_library[el]:
        if item['title'] == opinionated_choice.get(el):
            save(el, item['data'])
            print('Saved %s' % item['title'])
            break