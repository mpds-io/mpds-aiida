import tempfile
from aiida import orm
from aiida.engine import WorkChain, ToContext
from aiida.orm import Code, Dict, SinglefileData
from aiida_crystal_dft.workflows.base import BasePropertiesWorkChain

from aiida_crystal_dft.io.f9 import Fort9
import os


class CustomPropertiesWorkChain(BasePropertiesWorkChain):
    def _set_default_parameters(self, parameters):
        """Transform the input parameters by setting defaults for missing values."""
        parameters_dict = parameters.get_dict()
        
        # Despte the fact that we have the content of fort.9 in memory, 
        # we need to provide it to Fort9 in a way it can read
        # If Fort9 can accept a file-like object, we can use io.BytesIO
        with self.inputs.wavefunction.open(mode='rb') as f:

            # TODO: check if Fort9 can accept file-like objects directly. If not, we will need to create a temporary file.
            try:
                wf = Fort9(f)  # trying to initialize Fort9 with a file-like object
            except TypeError:
                import tempfile
                import os
                with tempfile.TemporaryDirectory() as tmpdir:
                    fort9_path = os.path.join(tmpdir, 'fort.9')
                    # copy content of the file-like object to a temporary file
                    with open(fort9_path, 'wb') as dst:
                        dst.write(f.read())
                    wf = Fort9(fort9_path)

        # standard defaults for band and dos calculations
        if 'band' in parameters_dict:
            if 'bands' not in parameters_dict['band']:
                self.logger.info('Proceeding with automatic generation of k-points path')
                structure = wf.get_structure()
                from aiida_crystal_dft.utils.kpoints import get_shrink_kpoints_path
                shrink, points, path = get_shrink_kpoints_path(structure)
                parameters_dict['band']['shrink'] = shrink
                parameters_dict['band']['bands'] = path
            if 'first' not in parameters_dict['band']:
                parameters_dict['band']['first'] = 1
            if 'last' not in parameters_dict['band']:
                parameters_dict['band']['last'] = wf.get_ao_number()

        if 'dos' in parameters_dict:
            if ('projections_atoms' not in parameters_dict['dos'] and
                'projections_orbitals' not in parameters_dict['dos']):
                self.logger.info('Proceeding with automatic generation of dos atomic projections')
                from aiida_crystal_dft.utils.dos import get_dos_projections_atoms
                parameters_dict['dos']['projections_atoms'] = get_dos_projections_atoms(wf.get_atomic_numbers())
            if 'first' not in parameters_dict['dos']:
                parameters_dict['dos']['first'] = 1
            if 'last' not in parameters_dict['dos']:
                parameters_dict['dos']['last'] = wf.get_ao_number()

        from aiida_crystal_dft.utils import get_data_class
        return get_data_class('dict')(dict=parameters_dict)



class MPDSPropertiesWorkChain(WorkChain):

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('code', valid_type=Code)
        spec.input('crystal_calc_uuid', valid_type=orm.Str)
        spec.input('parameters', valid_type=Dict, required=False)
        spec.input('options', valid_type=Dict, required=False)
        spec.outline(cls.prepare_wavefunction, cls.run_properties, cls.finalize)
        spec.expose_outputs(CustomPropertiesWorkChain)

    def prepare_wavefunction(self):
        calc = orm.load_node(self.inputs.crystal_calc_uuid.value)

        if 'retrieved' not in calc.outputs:
            self.report("Calculation does not contain retrieved")
            return self.exit_codes.ERROR_NO_RETRIEVED

        retrieved = calc.outputs.retrieved
        if 'fort.9' not in retrieved.list_object_names():
            self.report("fort.9 not found in retrieved")
            return self.exit_codes.ERROR_NO_FORT9

        with retrieved.open('fort.9', mode='rb') as f:
            content = f.read()

        with tempfile.NamedTemporaryFile(delete=False, suffix='.fort9') as tmp:
            tmp.write(content)
            tmp.flush()
            fort9 = SinglefileData(tmp.name, filename='fort.9').store()
            os.unlink(tmp.name)

        self.ctx.fort9 = fort9
        self.report(f"Created SinglefileData PK={fort9.pk} with file fort.9")

    def run_properties(self):
        default_resources = {
            'num_machines': 1,
            'num_mpiprocs_per_machine': 1,
        }
        default_options = {
            'resources': default_resources,
            'max_wallclock_seconds': 3600,
        }

        if 'options' in self.inputs:
            options_node = self.inputs.options
        else:
            options_node = Dict(dict=default_options)

        inputs = {
            'code': self.inputs.code,
            'wavefunction': self.ctx.fort9,
            'parameters': self.inputs.get('parameters', Dict(dict={})),
            'options': options_node,
        }
        future = self.submit(CustomPropertiesWorkChain, **inputs)
        return ToContext(properties=future)

    def finalize(self):
        calc = self.ctx.properties
        if not calc.is_finished_ok:
            self.report(f"Calculation of properties finished with error {calc.exit_status}")
            return
        self.out_many(self.exposed_outputs(calc, CustomPropertiesWorkChain))