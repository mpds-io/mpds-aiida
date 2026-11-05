import os
import time

import numpy as np
from aiida.engine import ExitCode
from aiida.orm import Dict
from aiida_crystal_dft.utils import recursive_update
from httplib2 import ServerNotFoundError
from mpds_client import APIError, MPDSDataRetrieval

from mpds_aiida.workflows.abacus_base import MPDSAbacusWorkChain

from ..common import get_template
from ..chemical_formulae import parse_formula


def matches_composition(structure, formula):
    expected = parse_formula(formula)
    actual = parse_formula(structure.get_chemical_formula())
    if set(actual) != set(expected) or not expected:
        return False
    scale = sum(actual.values()) / sum(expected.values())
    return all(
        np.isclose(actual[element], scale * count, rtol=1e-10, atol=1e-10)
        for element, count in expected.items()
    )


class MPDSAbacusStructureWorkChain(MPDSAbacusWorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("mpds_query", valid_type=Dict, required=True)
        spec.inputs.pop("structure")
        spec.inputs.pop("phase_label")

        spec.exit_code(501, "ERROR_NO_MPDS_API_KEY", message="MPDS API key not set")
        spec.exit_code(502, "ERROR_API_ERROR", message="MPDS API Error")
        spec.exit_code(503, "ERROR_NO_HITS", message="Request returned nothing")
        spec.exit_code(
            505,
            "ERROR_COMPOSITION_MISMATCH",
            message="No MPDS structure matches the requested composition",
        )
        spec.exit_code(504, "ERROR_SERVER_NOT_FOUND", message="MPDS server not found")

    def init_inputs(self):
        struct_result = self.get_geometry()
        if isinstance(struct_result, ExitCode):
            return struct_result
        self.ctx.structure = struct_result
        self.ctx.phase_label = self._build_phase_label()

        # Load config file and options
        # (moved here from the base class, which requires structure and phase_label)
        config_path = self.inputs.config_file.value
        try:
            options = get_template(config_path)
        except Exception:
            raise FileNotFoundError(f"Config file '{config_path}' not found")

        user_opts = self.inputs.workchain_options.get_dict()
        if user_opts:
            recursive_update(options, user_opts)
        self.ctx.config = options

        # Load codes
        self.ctx.codes = {}
        for name, label in options["codes"].items():
            self.ctx.codes[name] = label

        # Flags
        engine_options = options["options"]
        self.ctx.need_phonons = engine_options.get("need_phonons", False)
        self.ctx.optimize = engine_options.get("optimize_structure", True)
        self.ctx.calculation = engine_options.get("calculation", "cell-relax")
        self.ctx.options_run = engine_options.get("run", {})

    def _build_phase_label(self):
        query = self.inputs.mpds_query.get_dict()
        if "formulae" not in query or "sgs" not in query:
            raise ValueError("Query must contain both 'formulae' and 'sgs'")
        formula = query["formulae"]
        sgs = query["sgs"]
        return f"{formula}/{sgs}"

    def get_geometry(self):

        max_retries = 5
        attempt = 0

        api_key = os.getenv("MPDS_KEY")
        if not api_key:
            return self.exit_codes.ERROR_NO_MPDS_API_KEY

        client = MPDSDataRetrieval(api_key=api_key)
        query_dict = self.inputs.mpds_query.get_dict()
        query_dict["props"] = "atomic structure"
        if "classes" in query_dict:
            query_dict["classes"] += ", non-disordered"
        else:
            query_dict["classes"] = "non-disordered"

        while attempt < max_retries:
            attempt += 1
            try:
                answer = client.get_data(
                    query_dict,
                    fields={"S": ["cell_abc", "sg_n", "basis_noneq", "els_noneq"]},
                )
                break
            except APIError as ex:
                if ex.code == 429 and attempt != max_retries:
                    delay = 2 * (2 * attempt)
                    time.sleep(delay)
                    continue
                else:
                    self.report(f"MPDS API error: {str(ex)} (after {attempt} attempts)")
                    return self.exit_codes.ERROR_API_ERROR
            except ServerNotFoundError:
                return self.exit_codes.ERROR_SERVER_NOT_FOUND

        structs = [client.compile_crystal(line, flavor="ase") for line in answer]
        structs = list(filter(None, structs))
        if not structs:
            return self.exit_codes.ERROR_NO_HITS

        structs = [s for s in structs if matches_composition(s, query_dict["formulae"])]
        if not structs:
            return self.exit_codes.ERROR_COMPOSITION_MISMATCH

        minimal_struct = min(len(s) for s in structs)
        candidates = [s for s in structs if len(s) == minimal_struct]
        cells = np.array([s.get_cell().reshape(9) for s in candidates])
        median_cell = np.median(cells, axis=0)
        median_idx = int(np.argmin(np.linalg.norm(cells - median_cell, axis=1)))
        ase_struct = candidates[median_idx]

        from aiida.plugins import DataFactory

        return DataFactory("core.structure")(ase=ase_struct)
