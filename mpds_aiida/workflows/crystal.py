"""
The base workflow for AiiDA combining CRYSTAL and MPDS
"""
import os
from abc import abstractmethod
from aiida.engine import WorkChain, if_
from aiida.common.extendeddicts import AttributeDict
from aiida.orm.nodes.data.base import to_aiida_type
from aiida_crystal_dft.utils import get_data_class
from aiida_crystal_dft.workflows.base import BaseCrystalWorkChain, BasePropertiesWorkChain
from .. import TEMPLATE_DIR
from . import GEOMETRY_LABEL, PHONON_LABEL, ELASTIC_LABEL, PROPERTIES_LABEL


class MPDSCrystalWorkChain(WorkChain):
    """ A workchain enclosing all calculations for getting as much data from Crystal runs as we can
    """
    OPTIONS_FILES = {
        'default': 'production.yml',
        'metallic': 'metallic.yml',
        'nonmetallic': 'nonmetallic.yml'
    }
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
                   help="Calculation options",
                   serializer=to_aiida_type)
        spec.input('check_for_bond_type',
                   valid_type=get_data_class('bool'),
                   required=False,
                   default=True,
                   help="Check if we are to guess bonding type of the structure and choose defaults based on it",
                   non_db=True,
                   serializer=to_aiida_type)

        # define workchain routine
        spec.outline(cls.init_inputs,
                     cls.validate_inputs,
                     cls.optimize_geometry,
                     if_(cls.needs_phonons)(
                         cls.calculate_phonons),
                     cls.calculate_elastic_constants,
                     # correctly finalized
                     if_(cls.correctly_finalized("elastic_constants"))(
                         cls.print_exit_status),
                     if_(cls.needs_properties_run)(
                         cls.run_properties_calc),
                     cls.retrieve_results)

        # define outputs
        spec.expose_outputs(BaseCrystalWorkChain)
        spec.expose_outputs(BasePropertiesWorkChain)
        spec.output_namespace('aux_parameters', valid_type=get_data_class('dict'), required=False, dynamic=True)

    def needs_phonons(self):
        result = self.inputs.options.get_dict().get('need_phonons', self.DEFAULT['need_phonons'])
        self.ctx.need_phonons = result
        if not result:
            self.logger.warning("Skipping phonon frequency calculation")
        return result

    def needs_properties_run(self):
        if "properties_code" not in self.inputs:
            self.logger.warning("No properties code given as input, hence skipping electronic properties calculation")
            self.ctx.need_electronic_properties = False
            return False
        result = self.inputs.options.get_dict().get('need_properties', self.DEFAULT['need_electronic_properties'])
        self.ctx.need_electronic_properties = result
        if not result:
            self.logger.warning("Skipping electronic properties calculation")
        return result

    def init_inputs(self):
        # check that we actually have parameters, populate with defaults in not
        # 1) get the structure (label inn metadata.label!)
        self.ctx.inputs = AttributeDict()
        self.ctx.inputs.structure = self.get_geometry()
        # 2) find the bonding type if needed; if not just use default file
        if not self.inputs.check_for_bond_type:
            default_file = os.path.join(TEMPLATE_DIR, self.OPTIONS_FILES['default'])
            self.logger.info(f"Using {default_file} as default file")
        else:
            # check for the bonding type
            pass
        # self.ctx.inputs.crystal = AttributeDict()
        #
        # # set the crystal workchain inputs; structure is found by get_structure
        # self.ctx.inputs.crystal.code = self.inputs.crystal_code
        # self.ctx.inputs.crystal.basis_family = self.inputs.basis_family
        # self.ctx.inputs.crystal.structure = self.get_geometry()
        #
        # # set the properties workchain inputs
        # self.ctx.inputs.properties = AttributeDict()
        # self.ctx.inputs.properties.code = self.inputs.get('properties_code', None)
        # self.ctx.inputs.properties.parameters = self.inputs.get('properties_parameters', None)
        #
        # # properties wavefunction input must be set after crystal run
        # options_dict = self.inputs.options.get_dict()
        # self.ctx.need_elastic_constants = options_dict.get('need_elastic_constants',
        #                                                    self.DEFAULT['need_elastic_constants'])

    # def init_calc_inputs(self, calc_string):



    def validate_inputs(self):
        crystal_parameters = self.inputs.crystal_parameters.get_dict()
        geometry_parameters = crystal_parameters.pop('geometry')

        # We are going to do three CRYSTAL calculations. Let's prepare parameter inputs
        calc_keys = ['optimise', 'phonons', 'elastic_constants']
        assert all([x in geometry_parameters for x in calc_keys])
        self.ctx.crystal_parameters = AttributeDict()

        for key in calc_keys:
            self.ctx.crystal_parameters[key] = crystal_parameters.copy()
            self.ctx.crystal_parameters[key].update(
                {'geometry': {key: geometry_parameters[key]}}
            )

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

    def optimize_geometry(self):
        self.ctx.inputs.crystal.parameters = get_data_class('dict')(dict=self.ctx.crystal_parameters.optimise)
        self.ctx.inputs.crystal.options = get_data_class('dict')(dict=self.construct_metadata(GEOMETRY_LABEL))
        # noinspection PyTypeChecker
        crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
        return self.to_context(optimise=crystal_run)

    def calculate_phonons(self):
        self.ctx.inputs.crystal.structure = self.ctx.optimise.outputs.output_structure
        self.ctx.inputs.crystal.parameters = get_data_class('dict')(dict=self.ctx.crystal_parameters.phonons)
        self.ctx.inputs.crystal.options = get_data_class('dict')(
            dict=self.construct_metadata(PHONON_LABEL))
        # noinspection PyTypeChecker
        crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
        return self.to_context(phonons=crystal_run)

    def calculate_elastic_constants(self):
        if self.ctx.need_elastic_constants:
            # run elastic calc with optimised structure
            self.ctx.inputs.crystal.structure = self.ctx.optimise.outputs.output_structure
            options = self.construct_metadata(ELASTIC_LABEL)
            if "oxidation_states" in self.ctx.optimise.outputs:
                options["use_oxidation_states"] = self.ctx.optimise.outputs.oxidation_states.get_dict()
            self.ctx.inputs.crystal.parameters = get_data_class('dict')(
                dict=self.ctx.crystal_parameters.elastic_constants)
            self.ctx.inputs.crystal.options = get_data_class('dict')(dict=options)
            # noinspection PyTypeChecker
            crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
            return self.to_context(elastic_constants=crystal_run)

        else:
            self.logger.warning("Skipping elastic constants calculation")

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
