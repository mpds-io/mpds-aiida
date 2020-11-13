#  Copyright (c) Andrey Sobolev, 2020. Distributed under MIT license
"""
The MPDS workflow using structure from CIF file
"""
from aiida_crystal_dft.utils import get_data_class
from .crystal import MPDSCrystalWorkChain
from mpds_ml_labs.struct_utils import detect_format
from mpds_ml_labs.cif_utils import cif_to_ase


class CIFStructureWorkChain(MPDSCrystalWorkChain):

    @classmethod
    def define(cls, spec):
        super(CIFStructureWorkChain, cls).define(spec)
        # one required input: CIF input file name
        spec.input('structure', valid_type=get_data_class('str'), required=True)
        # 59X - CIF related errors
        spec.exit_code(590, 'ERROR_DISORDERED_STRUCTURE', message='Structure is disordered')
        spec.exit_code(591, 'ERROR_PARSING_CIF', message='Error in getting ASE object form CIF file')

    def get_geometry(self):
        """ Getting geometry from MPDS database
        """
        structure = open(self.inputs.structure).read()
        assert detect_format(structure) == 'cif'
        ase_obj, error = cif_to_ase(structure)
        if error:
            return self.exit_codes.ERROR_PARSING_CIF
        if 'disordered' in ase_obj.info:
            return self.exit_codes.ERROR_DISORDERED_STRUCTURE
        return get_data_class('structure')(ase=ase_obj)
