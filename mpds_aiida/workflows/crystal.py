"""
The base workflow for AiiDA combining CRYSTAL and MPDS
"""
from copy import deepcopy
from abc import abstractmethod
from aiida.engine import WorkChain, if_, while_
from aiida.common.extendeddicts import AttributeDict
from aiida.orm import Code
from aiida.orm.nodes.data.base import to_aiida_type
from aiida_crystal_dft.utils import get_data_class, recursive_update
from aiida_crystal_dft.workflows.base import BaseCrystalWorkChain, BasePropertiesWorkChain
from ..common import guess_metal, get_template


class MPDSCrystalWorkChain(WorkChain):
    """ A workchain enclosing all calculations for getting as much data from Crystal runs as we can
    """
    OPTIONS_FILES = {
        'default': 'production.yml',
        'metallic': 'metallic.yml',
        'nonmetallic': 'nonmetallic.yml'
    }
    # options related to this workchain (need_* included!) Other options get sent down the pipe
    OPTIONS_WORKCHAIN = ('optimize_structure', 'recursive_update')

    @classmethod
    def define(cls, spec):
        super(MPDSCrystalWorkChain, cls).define(spec)

        # just one optional input with the YML file contents in which all the options are stored
        # if input is not given, it is taken from the default location
        # it is possible to give incomplete parameters, they will be completed with defaults
        spec.input('workchain_options',
                   valid_type=get_data_class('dict'),
                   required=False,
                   default=lambda: get_data_class('dict')(dict={}),
                   help="Calculation options",
                   serializer=to_aiida_type)
        spec.input('check_for_bond_type',
                   valid_type=get_data_class('bool'),
                   required=False,
                   default=lambda: get_data_class('bool')(True),
                   help="Check if we are to guess bonding type of the structure and choose defaults based on it",
                   serializer=to_aiida_type)

        # define workchain routine
        spec.outline(cls.init_inputs,
                     while_(cls.has_calc_to_run)(
                         if_(cls.is_needed)(
                             cls.run_calc,
                             cls.check_and_get_results
                         )
                     ))

        # define outputs
        spec.expose_outputs(BaseCrystalWorkChain, exclude=('output_parameters', ))
        spec.expose_outputs(BasePropertiesWorkChain)
        spec.output_namespace('output_parameters', valid_type=get_data_class('dict'), required=False, dynamic=True)
        spec.exit_code(410, 'INPUT_ERROR', 'Error in input')
        spec.exit_code(411, 'ERROR_INVALID_CODE', 'Non-existent code is given')
        spec.exit_code(412, 'ERROR_OPTIMIZATION_FAILED', 'Structure optimization failed!')

    def init_inputs(self):
        # check that we actually have parameters, populate with defaults in not
        # 1) get the structure (label in metadata.label!)
        self.ctx.codes = AttributeDict()
        self.ctx.structure = self.get_geometry()
        # 2) find the bonding type if needed; if not just use default file
        if not self.inputs.check_for_bond_type:
            default_file = self.OPTIONS_FILES['default']
            self.report(f"Using {default_file} as default file")
        else:
            # check for the bonding type
            is_metallic = guess_metal(self.ctx.structure.get_ase())
            if is_metallic:
                default_file = self.OPTIONS_FILES['metallic']
                self.report(f"Guessed metallic bonding; using {default_file} as default file")
            else:
                default_file = self.OPTIONS_FILES['nonmetallic']
                self.report(f"Guessed nonmetallic bonding; using {default_file} as default file")
        options = get_template(default_file)
        # update with workchain options, if present (recursively if needed)
        changed_options = self.inputs.workchain_options.get_dict()
        needs_recursive_update = changed_options['options'].get('recursive_update',
                                                                options['options'].get('recursive_update', True))
        if changed_options:
            if needs_recursive_update:
                recursive_update(options, changed_options)
            else:
                options.update(changed_options)
        self.validate_inputs(options)
        # put options to context
        self.ctx.codes.update({k: Code.get_from_string(v) for k, v in options['codes'].items()})
        self.ctx.basis_family = options['basis_family']
        # dealing with calculations
        calculations = list(options['calculations'].keys())
        if 'optimize_structure' in options['options']:
            optimization = options['options']['optimize_structure']
            if optimization not in calculations:
                self.report('Optimization procedure not in calculations list!')
                return self.exit_codes.INPUT_ERROR
            idx = calculations.index(optimization)
            if idx != 0:
                calculations.insert(0, calculations.pop(idx))
        self.ctx.calculations = calculations
        # Pre calc stuff
        self.ctx.metadata = AttributeDict()
        self.ctx.inputs = AttributeDict()
        for c in calculations:
            c_metadata = {k: deepcopy(v) for k, v in options['options'].items()
                          if ('need_' not in k or c in k) and (k not in self.OPTIONS_WORKCHAIN)}
            # add label, calculation type, resources if not given
            c_metadata['label'] = options['calculations'][c]['metadata']['label']
            # specially for yascheduler users
            if 'resources' not in c_metadata:
                c_metadata['resources'] = {'num_machines': 1, 'num_mpiprocs_per_machine': 2}
            if any([len(options['calculations'][c]['parameters'].keys()) != 1 for c in calculations]):
                self.report('Calculations must have a definite type!')
                return self.exit_codes.INPUT_ERROR
            c_metadata['calc_type'] = list(options['calculations'][c]['parameters'].keys())[0]
            if 'optimize_structure' in options['options']:
                c_metadata['optimize_structure'] = (options['options']['optimize_structure'] == c)
            else:
                c_metadata['optimize_structure'] = None
            self.ctx.metadata[c] = c_metadata
            c_input = deepcopy(options['default'])
            recursive_update(c_input, options['calculations'][c]['parameters'])
            self.ctx.inputs[c] = c_input
        self.ctx.running_calc = -1
        self.ctx.running_calc_type = None
        self.ctx.is_optimization = False

    def validate_inputs(self, options):
        valid_keys = ('codes', 'options', 'basis_family', 'default', 'calculations')
        if set(options.keys()) != set(valid_keys):
            self.report('Input validation failed!')
            return self.exit_codes.INPUT_ERROR

    @abstractmethod
    def get_geometry(self):
        raise NotImplemented

    def has_calc_to_run(self):
        self.ctx.running_calc += 1
        if self.ctx.running_calc == len(self.ctx.calculations):
            return False
        return True

    def is_needed(self):
        calculation = self.ctx.calculations[self.ctx.running_calc]
        is_calc_needed = self.ctx.metadata[calculation].get(f'need_{calculation}', True)
        if not is_calc_needed:
            self.report(f'Calculation {calculation} is not needed due to need_* flag; skipping')
        return is_calc_needed

    # def needs_properties_run(self):
    #     if "properties_code" not in self.inputs:
    #         self.logger.warning("No properties code given as input, hence skipping electronic properties calculation")
    #         self.ctx.need_electronic_properties = False
    #         return False
    #     result = self.inputs.options.get_dict().get('need_properties', self.DEFAULT['need_electronic_properties'])
    #     self.ctx.need_electronic_properties = result
    #     if not result:
    #         self.logger.warning("Skipping electronic properties calculation")
    #     return result

    def run_calc(self):
        calculation = self.ctx.calculations[self.ctx.running_calc]
        calc_type = self.ctx.metadata[calculation].pop('calc_type')
        if calc_type not in ('crystal', 'properties'):
            self.report(f'{calculation}: Unsupported calculation type {calc_type} in input; exiting!')
            return self.exit_codes.INPUT_ERROR
        self.ctx.running_calc_type = calc_type
        return self._run_calc_crystal() if calc_type == 'crystal' else self._run_calc_properties()

    def _run_calc_crystal(self):
        calculation = self.ctx.calculations[self.ctx.running_calc]
        inputs = BaseCrystalWorkChain.get_builder()
        if 'crystal' not in self.ctx.codes:
            self.report('CRYSTAL code not given as input; exiting!')
            return self.exit_codes.ERROR_INVALID_CODE
        inputs.code = self.ctx.codes['crystal']
        metadata = self.ctx.metadata[calculation]
        optimization = metadata.pop('optimize_structure')
        self.ctx.is_optimization = optimization
        if optimization is None or optimization:
            self.report(f'{calculation}: Using structure from input')
            inputs.structure = self.ctx.structure
        else:
            self.report(f'{calculation}: Using optimized structure')
            inputs.structure = self.ctx.optimized_structure
        inputs.basis_family, _ = get_data_class('crystal_dft.basis_family').get_or_create(self.ctx.basis_family)
        inputs.parameters = get_data_class('dict')(dict=self.ctx.inputs[calculation]['crystal'])
        workchain_label = self.inputs.metadata.get('label', 'CRYSTAL calc')
        calc_label = metadata.pop('label') if 'label' in metadata else calculation

        if 'oxidation_states' in self.ctx:
            self.report(f"{calculation}: Using oxidation states {self.ctx.oxidation_states} in {calculation}")
            metadata["use_oxidation_states"] = self.ctx.oxidation_states
        inputs.options = get_data_class('dict')(dict=metadata)
        inputs.metadata = {
            'label': f"{workchain_label}: {calc_label}",
            'description': self.inputs.metadata.get('description', '')
        }
        # noinspection PyTypeChecker
        crystal_run = self.submit(BaseCrystalWorkChain, **inputs)
        return self.to_context(**{calculation: crystal_run})

    def _run_calc_properties(self):
        raise NotImplemented

    def check_and_get_results(self):
        calculation = self.ctx.calculations[self.ctx.running_calc]
        calc = self.ctx.get(calculation)
        ok_finish = calc.is_finished_ok
        # check if this was optimization
        is_optimization = self.ctx.is_optimization
        if is_optimization:
            if not ok_finish:
                return self.exit_codes.ERROR_OPTIMIZATION_FAILED
            self.out_many(self.exposed_outputs(calc, BaseCrystalWorkChain))
        if ok_finish:
            self.out(f'output_parameters.{calculation}', calc.outputs.output_parameters)
        else:
            self.report(f'{calculation} has failed, no outputs are exposed')

    # @staticmethod
    # def correctly_finalized(calc_string):
    #     def wrapped(self):
    #         assert calc_string in self.CALC_STRINGS
    #         if not hasattr(self.ctx, calc_string):
    #             return False
    #         calc = self.ctx.get(calc_string)
    #         return calc.is_finished_ok
    #
    #     return wrapped

    # def run_properties_calc(self):
    #     self.ctx.inputs.properties.wavefunction = self.ctx.optimise.outputs.output_wavefunction
    #     self.ctx.inputs.properties.options = get_data_class('dict')(
    #         dict=self.construct_metadata(PROPERTIES_LABEL))
    #     # noinspection PyTypeChecker
    #     properties_run = self.submit(BasePropertiesWorkChain, **self.ctx.inputs.properties)
    #     return self.to_context(properties=properties_run)
