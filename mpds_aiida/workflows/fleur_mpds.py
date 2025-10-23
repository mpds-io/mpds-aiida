import os
import time
import random
import numpy as np
from aiida.engine import ExitCode
from aiida.orm import Dict
from aiida_crystal_dft.utils import get_data_class
from mpds_client import MPDSDataRetrieval, APIError
from httplib2 import ServerNotFoundError
from .fleur_base import MPDSFleurWorkChain


class MPDSFleurStructureWorkChain(MPDSFleurWorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('mpds_query', valid_type=Dict, required=True)
        spec.inputs.pop('structure')
        spec.inputs.pop('phase_label')

        spec.exit_code(501, 'ERROR_NO_MPDS_API_KEY', message='MPDS API key not set')
        spec.exit_code(502, 'ERROR_API_ERROR', message='MPDS API Error')
        spec.exit_code(503, 'ERROR_NO_HITS', message='Request returned nothing')
        spec.exit_code(504, 'ERROR_SERVER_NOT_FOUND', message='MPDS server not found')

    def init_inputs(self):
        struct_result = self.get_geometry()
        if isinstance(struct_result, ExitCode):
            return struct_result

        self.ctx.structure = struct_result
        self.ctx.phase_label = self._build_phase_label()

        # Initialize other inputs from parent
        super().init_inputs()

    def _build_phase_label(self):
        query = self.inputs.mpds_query.get_dict()
        formula = query.get('formulae', 'unknown')
        sgs = query.get('sgs', 'unknown')
        return f"{formula}/{sgs}"

    def get_geometry(self):

        max_retries = 5
        attempt = 0

        api_key = os.getenv('MPDS_KEY')
        if not api_key:
            return self.exit_codes.ERROR_NO_MPDS_API_KEY

        client = MPDSDataRetrieval(api_key=api_key)
        query_dict = self.inputs.mpds_query.get_dict()
        query_dict['props'] = 'atomic structure'
        if 'classes' in query_dict:
            query_dict['classes'] += ', non-disordered'
        else:
            query_dict['classes'] = 'non-disordered'

        while attempt < max_retries:
            attempt += 1
            try:
                answer = client.get_data(
                    query_dict,
                    fields={'S': ['cell_abc', 'sg_n', 'basis_noneq', 'els_noneq']}
                )
                break
            except APIError as ex:
                if ex.code == 429 and attempt != max_retries:
                    delay = 2 * (2 * attempt)
                    time.sleep(delay)
                    continue
                else:
                    # Raise error when attemp == max_retries or other API errors
                    self.report(f'MPDS API error: {str(ex)} (after {attempt} attempts)')
                    return self.exit_codes.ERROR_API_ERROR
            except ServerNotFoundError:
                return self.exit_codes.ERROR_SERVER_NOT_FOUND

        structs = [client.compile_crystal(line, flavor='ase') for line in answer]
        structs = list(filter(None, structs))
        if not structs:
            return self.exit_codes.ERROR_NO_HITS

        minimal_struct = min(len(s) for s in structs)
        candidates = [s for s in structs if len(s) == minimal_struct]
        cells = np.array([s.get_cell().reshape(9) for s in candidates])
        median_cell = np.median(cells, axis=0)
        median_idx = int(np.argmin(np.linalg.norm(cells - median_cell, axis=1)))
        ase_struct = candidates[median_idx]

        return get_data_class('structure')(ase=ase_struct)