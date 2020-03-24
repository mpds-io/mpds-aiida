"""
This script parses and downloads the CRYSTAL online
basis set library and for each chemical element
selects and saves a single appropriate basis set
"""
import os
from ase.data import chemical_symbols
from pycrystal import download_basis_library

bs_library = download_basis_library()

FOLDER = 'MPDSBSL'
assert not os.path.exists(FOLDER)
os.makedirs(FOLDER)

saved = set()

def save(el, content):
    assert not os.path.exists('%s/%s.basis' % (FOLDER, el))
    with open('%s/%s.basis' % (FOLDER, el), 'w') as f:
        f.write(content + "\n")
    saved.add(el)

for el in sorted(bs_library.keys()):
    #print("%s -> %s BS" % (el, len(bs_library[el])))
    eidx = chemical_symbols.index(el)

    if len(bs_library[el]) == 1:
        save(el, gbasis['data'])
        continue

    if 56 < eidx < 72 or 88 < eidx < 104: # f-elements
        for gbasis in bs_library[el]:
            title = gbasis['title'].lower()
            if 'no_g' in title:
                save(el, gbasis['data'])
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

print('--- TO DO MANUAL CHOICE ---')
unsaved = set(bs_library.keys()) - saved
for el in unsaved:
    print(el, [item['title'] for item in bs_library[el]])