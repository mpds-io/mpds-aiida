#  Copyright (c) Andrey Sobolev, 2020. Distributed under MIT license
"""
The MPDS workflow using AiiDA StructureData object
"""
from aiida_crystal_dft.utils import get_data_class
from .crystal import MPDSCrystalWorkChain


class AiidaStructureWorkChain(MPDSCrystalWorkChain):

    @classmethod
    def define(cls, spec):
        super(AiidaStructureWorkChain, cls).define(spec)
        # one required input: AiiDA structure
        spec.input('structure', valid_type=get_data_class('structure'), required=True)

    def get_geometry(self):
        """ Getting geometry from MPDS database
        """
        return self.inputs.structure
