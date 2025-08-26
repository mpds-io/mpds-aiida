from ab_initio_calculations.utils.fleur_utils import Fleur_setup
from aiida import load_profile
from aiida.plugins import DataFactory

from mpds_aiida.utils.magmoms import (
    ase_to_prim,
    ase_to_struct_prim,
    reverse_structure_data,
    convert_xml_to_FleurInpData
)

from mpds_aiida.workflows.phonopy_fleur import PhonopyFleurWorkChain, FleurForcesWorkChain

from ase.build import bulk

load_profile()

def test_fleur_inp_1():
    atoms = bulk('Fe', 'fcc', a=3.60899, orthorhombic=True)
    # Crystallographic structure
    fleur_setup = Fleur_setup(atoms)
    error = fleur_setup.validate()
    if error:
        print(f"Validation error: {error}")
    else:
        xml_input = fleur_setup.get_input_setup(label="Fe_fcc")
        print(xml_input) # No magmoms 2 atoms

def test_fleur_inp_2():
    atoms = bulk('Fe', 'bcc', a=3.60899, orthorhombic=True)
    
    """The ase.build.bulk function for magnetic elements (like Fe)
       automatically sets default magnetic moments for atoms."""

    new_atoms = ase_to_prim(atoms)
    fleur_setup = Fleur_setup(new_atoms)
    error = fleur_setup.validate()
    if error:
        print(f"Validation error: {error}")
    else:
        xml_input = fleur_setup.get_input_setup(label="Fe_fcc")
        print(xml_input) # 2.3 magmom one atom

def test_fleur_inp_3():
    atoms = bulk('Fe', 'bcc', a=3.60899, orthorhombic=True)
    atoms.set_initial_magnetic_moments([1.7, -1.7])
    # Primitive structure
    new_atoms = ase_to_prim(atoms)
    fleur_setup = Fleur_setup(new_atoms)
    error = fleur_setup.validate()
    if error:
        print(f"Validation error: {error}")
    else:
        xml_input = fleur_setup.get_input_setup(label="Fe_fcc")
        print(xml_input) # Two atoms. Good


def test_phonopy_fleur_with_magmoms_1():
    # Get tags allows to restore kinds of the atoms
    atoms = bulk('Fe', 'fcc', a=3.60899, orthorhombic=True)
    atoms.set_initial_magnetic_moments([1.7, -1.7])
    atoms_prim = ase_to_prim(atoms)
    st, mp = ase_to_struct_prim(atoms_prim)

    PreProcessData = DataFactory("phonopy.preprocess")
    supercell_matrix = [2,2,2]
    preprocess_data =  PreProcessData(structure=st, supercell_matrix=supercell_matrix)

    supercells = preprocess_data.get_supercells_with_displacements()

    sc_atoms = reverse_structure_data(supercells['supercell_1'], mp)
    fleur_setup = Fleur_setup(sc_atoms)
    error = fleur_setup.validate()
    if error:
        print(f"Validation error: {error}")
    else:
        xml_input = fleur_setup.get_input_setup(label="Fe_fcc")
        print(xml_input) # Check it by atomic coordinates

def test_phonopy_fleur_with_magmoms_2():
    # Get tags allows to restore kinds of the atoms
    atoms = bulk('Fe', 'fcc', a=3.60899, orthorhombic=True)
    atoms.set_initial_magnetic_moments([1.7, 1.7])
    atoms_prim = ase_to_prim(atoms)
    st, mp = ase_to_struct_prim(atoms_prim)

    PreProcessData = DataFactory("phonopy.preprocess")
    supercell_matrix = [2,2,2]
    preprocess_data =  PreProcessData(structure=st, supercell_matrix=supercell_matrix)

    supercells = preprocess_data.get_supercells_with_displacements()

    preprocess_data.get_phonopy_instance()

    sc_atoms = reverse_structure_data(supercells['supercell_1'], mp)
    fleur_setup = Fleur_setup(sc_atoms)
    error = fleur_setup.validate()
    if error:
        print(f"Validation error: {error}")
    else:
        xml_input = fleur_setup.get_input_setup(label="Fe_fcc")
        print(xml_input) # Check it by atomic coordinates

def test_phonopy_fleur_with_magmoms_3():
    # Get tags allows to restore kinds of the atoms
    atoms = bulk('Fe', 'fcc', a=3.60899, orthorhombic=True)
    atoms.set_initial_magnetic_moments([[0, 0, 2.3], [0, 0, -2.3]])
    atoms_prim = ase_to_prim(atoms)
    st, mp = ase_to_struct_prim(atoms_prim)

    PreProcessData = DataFactory("phonopy.preprocess")
    supercell_matrix = [2,2,2]
    preprocess_data =  PreProcessData(structure=st, supercell_matrix=supercell_matrix)

    supercells = preprocess_data.get_supercells_with_displacements()

    preprocess_data.get_phonopy_instance()
    # Do not use mapping from this directly
    # Make sure they have same numeration as supercells
    supercells_pha = preprocess_data.get_phonopy_instance().supercells_with_displacements
    # After correct numeration, put it into ForceCalculations
    print(len(supercells_pha)) # Returns 2

    sc_atoms = reverse_structure_data(supercells['supercell_1'], mp)
    fleur_setup = Fleur_setup(sc_atoms)
    error = fleur_setup.validate()
    if error:
        print(f"Validation error: {error}")
    else:
        xml_input = fleur_setup.get_input_setup(label="Fe_fcc")
        print(xml_input) # Check it by atomic coordinates

def test_forces_magmoms():
    from aiida.orm import Dict, Str
    from aiida.engine import run


    from aiida import load_profile

    load_profile()

    atoms = bulk('Fe', 'fcc', a=3.60899, orthorhombic=True)
    atoms.set_initial_magnetic_moments([1.7, -1.7])
    atoms_prim = ase_to_prim(atoms)
    # st, mp = ase_to_struct_prim(atoms_prim)

    fleur_setup = Fleur_setup(atoms_prim)
    error = fleur_setup.validate()
    if error:
        print(f"Validation error: {error}")
    else:
        xml_input = fleur_setup.get_input_setup(label="Fe_fcc_AFM")
        last_20_lines = xml_input.split('\n')[-20:] # Get the last 20 lines
        for line in last_20_lines:
            print(line)
        fleur_inp_data = convert_xml_to_FleurInpData(xml_input)

    # setup FleurScfWorkChain inputs

    wf_relax_scf = Dict(dict={
            'fleur_runmax': 1,
            'itmax_per_run': 50})

    # Submit FleurScfWorkChain
    future = run(
        FleurForcesWorkChain,
        fleur = Str('fleur'),
        fleurinp = fleur_inp_data,
        wf_parameters = wf_relax_scf,
    )
    print(f"finished: {future.node_pk}")

def test_phonopy_magmoms():
    from aiida.orm import Dict, Str, Bool, load_code
    from aiida.engine import run_get_node


    from aiida import load_profile

    load_profile()

    atoms = bulk('Fe', 'fcc', a=3.60899, orthorhombic=True)
    atoms.set_initial_magnetic_moments([1.7, -1.7])
    atoms_prim = ase_to_prim(atoms)
    st, mp = ase_to_struct_prim(atoms_prim)

    # setup FleurScfWorkChain inputs

    wf_relax_scf = {
            'fleur_runmax': 1,
            'itmax_per_run': 50
            }

    settings = {
        "fleur": 'fleur',
        "settings": {"additional_retrieve_list": ["FORCES"]},
        "wf_parameters": wf_relax_scf,
    }

    print(mp)

    inputs = {
        "structure": st,
        "magmoms_mapper": mp,
        "fleur_parameters": settings,
        "supercell_matrix": [[2, 0, 0], [0, 2, 0], [0, 0, 2]],
        "test_magmoms_run": Bool(True),
        "phonopy": {
            "code": load_code("phonopy@local_machine"),
            "parameters": Dict({"band": "auto"}),
        }}

    results, node = run_get_node(PhonopyFleurWorkChain, **inputs)
    # h = node.outputs.phonopy_data.get_phonopy_instance()
    # ph.produce_force_constants()
    # ph.auto_band_structure(plot=True).savefig("F_AFM_band_structure.png")
    

if __name__ == "__main__":
    # test_fleur_inp_1()
    # test_fleur_inp_3()
    # test_phonopy_fleur_with_magmoms_3()
    # test_forces_magmoms()
    test_phonopy_magmoms()
    pass