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
from . import PROPERTIES_LABEL


class MPDSCrystalWorkChain(WorkChain):
    """ A workchain enclosing all calculations for getting as much data from Crystal runs as we can
    """
    OPTIONS_FILES = {
        'default': 'production.yml',
        'metallic': 'metallic.yml',
        'nonmetallic': 'nonmetallic.yml'
    }
    # options related to this workchain (needs_* included!) Other options get sent down the pipe
    OPTIONS_WORKCHAIN = ('optimize_structure', 'recursive_update')

    # DEFAULT = {'need_phonons': True,
    #            'need_elastic_constants': True,
    #            'need_electronic_properties': True}
    #
    # CALC_STRINGS = ("optimise", "phonons", "elastic_constants", "electronic_properties")

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
                   help="Check if we are to guess bonding type of the structure and choose defaults based on it")

        # define workchain routine
        spec.outline(cls.init_inputs,
                     while_(cls.has_calc_to_run)(
                         if_(cls.needs_)(
                             cls.run_calc
                         )
                     ),
                     # correctly finalized
                     if_(cls.correctly_finalized("elastic_constants"))(
                         cls.print_exit_status),
                     cls.retrieve_results)

        # define outputs
        spec.expose_outputs(BaseCrystalWorkChain)
        spec.expose_outputs(BasePropertiesWorkChain)
        spec.output_namespace('aux_parameters', valid_type=get_data_class('dict'), required=False, dynamic=True)
        spec.exit_code(410, 'INPUT_ERROR', 'Error in input')
        spec.exit_code(411, 'ERROR_INVALID_CODE', 'Non-existent code is given')

    def init_inputs(self):
        # check that we actually have parameters, populate with defaults in not
        # 1) get the structure (label in metadata.label!)
        self.ctx.codes = AttributeDict()
        self.ctx.inputs = AttributeDict()
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
        # Pre calc stuff (TODO: all the metadata!)
        self.ctx.metadata = AttributeDict()
        self.ctx.inputs = AttributeDict()
        self.ctx.labels.update({c: options['calculations'][c]['metadata']['label'] for c in calculations})
        for c in calculations:
            c_input = deepcopy(options['default'])
            recursive_update(c_input, options['calculations'][c]['parameters'])
            self.ctx.inputs[c] = c_input

    def validate_inputs(self, options):
        valid_keys = ('codes', 'options', 'basis_family', 'default', 'calculations')
        if set(options.keys()) != set(valid_keys):
            self.report('Input validation failed!')
            return self.exit_codes.INPUT_ERROR

    def construct_metadata(self, calc_string):
        options_dict = self.inputs.options.get_dict()
        unneeded_keys = [k for k in options_dict if "need_" in k]
        for k in unneeded_keys:
            options_dict.pop(k)

        # label and description
        label = self.inputs.metadata.get('label', '')
        description = self.inputs.metadata.get('description', '')
        metadata = {'description': description}
        if label:
            metadata['label'] = '{}: {}'.format(label, calc_string)
        metadata.update(options_dict)
        return metadata

    @abstractmethod
    def get_geometry(self):
        raise NotImplemented

    def has_calc_to_run(self):
        return NotImplemented

    def needs_(self):
        return NotImplemented

    # def needs_phonons(self):
    #     result = self.inputs.options.get_dict().get('need_phonons', self.DEFAULT['need_phonons'])
    #     self.ctx.need_phonons = result
    #     if not result:
    #         self.logger.warning("Skipping phonon frequency calculation")
    #     return result
    #
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
        return NotImplemented

    # def optimize_geometry(self):
    #     self.ctx.inputs.crystal.parameters = get_data_class('dict')(dict=self.ctx.crystal_parameters.optimise)
    #     self.ctx.inputs.crystal.options = get_data_class('dict')(dict=self.construct_metadata(GEOMETRY_LABEL))
    #     # noinspection PyTypeChecker
    #     crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
    #     return self.to_context(optimise=crystal_run)
    #
    # def calculate_phonons(self):
    #     self.ctx.inputs.crystal.structure = self.ctx.optimise.outputs.output_structure
    #     self.ctx.inputs.crystal.parameters = get_data_class('dict')(dict=self.ctx.crystal_parameters.phonons)
    #     self.ctx.inputs.crystal.options = get_data_class('dict')(
    #         dict=self.construct_metadata(PHONON_LABEL))
    #     # noinspection PyTypeChecker
    #     crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
    #     return self.to_context(phonons=crystal_run)
    #
    # def calculate_elastic_constants(self):
    #     if self.ctx.need_elastic_constants:
    #         # run elastic calc with optimised structure
    #         self.ctx.inputs.crystal.structure = self.ctx.optimise.outputs.output_structure
    #         options = self.construct_metadata(ELASTIC_LABEL)
    #         if "oxidation_states" in self.ctx.optimise.outputs:
    #             options["use_oxidation_states"] = self.ctx.optimise.outputs.oxidation_states.get_dict()
    #         self.ctx.inputs.crystal.parameters = get_data_class('dict')(
    #             dict=self.ctx.crystal_parameters.elastic_constants)
    #         self.ctx.inputs.crystal.options = get_data_class('dict')(dict=options)
    #         # noinspection PyTypeChecker
    #         crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
    #         return self.to_context(elastic_constants=crystal_run)
    #
    #     else:
    #         self.logger.warning("Skipping elastic constants calculation")

    @staticmethod
    def correctly_finalized(calc_string):
        def wrapped(self):
            assert calc_string in self.CALC_STRINGS
            if not hasattr(self.ctx, calc_string):
                return False
            calc = self.ctx.get(calc_string)
            return calc.is_finished_ok

        return wrapped

    def print_exit_status(self):
        self.logger.info("Elastic calc correctly finalized: {}".format(
            self.correctly_finalized("elastic_constants")(self)))

    def run_properties_calc(self):
        self.ctx.inputs.properties.wavefunction = self.ctx.optimise.outputs.output_wavefunction
        self.ctx.inputs.properties.options = get_data_class('dict')(
            dict=self.construct_metadata(PROPERTIES_LABEL))
        # noinspection PyTypeChecker
        properties_run = self.submit(BasePropertiesWorkChain, **self.ctx.inputs.properties)
        return self.to_context(properties=properties_run)

    def retrieve_results(self):
        """ Expose all outputs of optimized structure and properties calcs
        """
        self.out_many(self.exposed_outputs(self.ctx.optimise, BaseCrystalWorkChain))
        if self.ctx.need_phonons:
            self.out('phonons_parameters', self.ctx.phonons.outputs.output_parameters)

        if self.ctx.need_elastic_constants:
            self.out('elastic_parameters', self.ctx.elastic_constants.outputs.output_parameters)

        if self.ctx.need_electronic_properties:
            self.out_many(self.exposed_outputs(self.ctx.properties, BasePropertiesWorkChain))


def _not(f):
    def wrapped(self):
        return not f(self)

    return wrapped
