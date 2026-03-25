"""
These are some utils for handling the CRYSTAL calculation inputs
https://www.crystal.unito.it
"""

def assert_conforming_input(content):
    return  'PBE0' in content \
        and 'XLGRID' in content \
        and 'TOLLDENS\n8' in content \
        and 'TOLLGRID\n16' in content \
        and 'TOLDEE\n9' in content


def get_raw_input_type(string):
    if 'MOLECULE' in string:
        return 'ISLD_ATOM'
    elif 'FREQCALC' in string:
        return 'PHONON'
    elif 'ELASTCON' in string or 'ELAPIEZO' in string:
        return 'ELASTIC'
    elif 'OPTGEOM' in string:
        return 'STRUCT'
    else:
        return None


def get_raw_output_type(calc):
    """
    TODO sync to dft-organizer
    """
    if calc.info['periodicity'] == 0x5:
        return 'ISLD_ATOM'
    elif calc.phonons['modes']:
        return 'PHONON'
    elif calc.elastic.get('K'):
        return 'ELASTIC'
    elif calc.tresholds:
        return 'STRUCT'
    else:
        return None


def get_input_prec(string):
    try:
        tol = tuple([ -int(x) for x in string.split('TOLINTEG')[-1].strip().split("\n")[0].split() ])
    except:
        tol = (-6, -6, -6, -6, -12) # default for CRYSTAL09-17
    try:
        kset = int(string.split('SHRINK')[-1].strip().split()[0])
    except:
        kset = None # molecule or isolated atom
    kset = tuple([kset] * 3)
    return tol, kset


def get_input_spin(string):
    spin = string.split('SPINLOCK')[-1].strip().split("\n")[0].strip().split()
    #assert int(spin[1]) > 50
    return int(spin[0])


def get_bs_fgpt(basis_set):

    multipliers = {'S': 10, 'SP': 100, 'P': 1000, 'D': 10000, 'F': 10000, 'G': 10000, 'H': 10000}
    bs_fgpt = {}

    for el in basis_set:
        bs_repr = []
        for channel in basis_set[el]:
            bs_repr.append([])
            for coeffs in channel[1:]:
                bs_repr[-1].append(sum([round(coeff, 1) * multipliers[channel[0]] for coeff in coeffs]))
            bs_repr[-1] = sum(bs_repr[-1])
        if sum(bs_repr) == 0:
            bs_repr = [1] # gives fgpt = 0
        bs_fgpt[el] = int(round(log(sum(bs_repr)) * 10000))

    return tuple(sorted([(key, value) for key, value in bs_fgpt.items()], key=lambda x: x[0]))
