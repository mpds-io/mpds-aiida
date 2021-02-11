#  Copyright (c) Andrey Sobolev, 2020. Distributed under MIT license
"""
The MPDS workflow for AiiDA that gets structure with MPDS query
"""
import os
import time
import random
import numpy as np

from aiida_crystal_dft.utils import get_data_class
from mpds_client import MPDSDataRetrieval, APIError
from .crystal import MPDSCrystalWorkChain


class MPDSStructureWorkChain(MPDSCrystalWorkChain):

    @classmethod
    def define(cls, spec):
        super(MPDSStructureWorkChain, cls).define(spec)
        # one required input: MPDS phase id
        spec.input('mpds_query', valid_type=get_data_class('dict'), required=True)
        # errors related to MPDS retrieval
        spec.exit_code(501, 'ERROR_NO_MPDS_API_KEY', message='MPDS API key not set')
        spec.exit_code(502, 'ERROR_API_ERROR', message='MPDS API Error')
        spec.exit_code(503, 'ERROR_NO_HITS', message='Request returned nothing')

    def get_geometry(self):
        """ Getting geometry from MPDS database
        """
        # check for API key
        api_key = os.getenv('MPDS_KEY')
        if not api_key:
            return self.exit_codes.ERROR_NO_MPDS_API_KEY
        client = MPDSDataRetrieval(api_key=api_key)

        query_dict = self.inputs.mpds_query.get_dict()
        # prepare query
        query_dict['props'] = 'atomic structure'
        if 'classes' in query_dict:
            query_dict['classes'] += ', non-disordered'
        else:
            query_dict['classes'] = 'non-disordered'

        try:
            answer = client.get_data(
                query_dict,
                fields={'S': [
                    'cell_abc',
                    'sg_n',
                    'basis_noneq',
                    'els_noneq'
                ]}
            )
        except APIError as ex:
            if ex.code == 429:
                self.logger.warning("Too many parallel MPDS requests, chilling")
                time.sleep(random.choice([2 * 2**m for m in range(5)]))
                return self.get_geometry()
            else:
                self.report(f'MPDS API error: {str(ex)}')
                self.logger.error(f'MPDS API error: {str(ex)}')
                return self.exit_codes.ERROR_API_ERROR

        structs = [client.compile_crystal(line, flavor='ase') for line in answer]
        structs = list(filter(None, structs))
        if not structs:
            return self.exit_codes.ERROR_NO_HITS
        minimal_struct = min([len(s) for s in structs])

        # get structures with minimal number of atoms and find the one with median cell vectors
        cells = np.array([s.get_cell().reshape(9) for s in structs if len(s) == minimal_struct])
        median_cell = np.median(cells, axis=0)
        median_idx = int(np.argmin(np.sum((cells - median_cell) ** 2, axis=1) ** 0.5))
        return get_data_class('structure')(ase=structs[median_idx])
