"""
The workflow for AiiDA combining CRYSTAL and MPDS
"""
import os
import numpy as np
from mpds_client import MPDSDataRetrieval

from aiida.engine import WorkChain
from aiida.orm import Code
from aiida.common.extendeddicts import AttributeDict
from aiida_crystal.aiida_compatibility import get_data_class
from aiida_crystal.workflows.base import BaseCrystalWorkChain, BasePropertiesWorkChain


class MPDSCrystalWorkchain(WorkChain):
    """ A workchain enclosing all calculations for getting as much data from Crystal runs as we can
    """
    DEFAULT = {'need_phonons': True,
               'need_elastic_constants': True,
               'need_electronic_properties': True}

    @classmethod
    def define(cls, spec):
        super(MPDSCrystalWorkchain, cls).define(spec)
        # define code inputs
        spec.input('crystal_code', valid_type=Code, required=True)
        spec.input('properties_code', valid_type=Code, required=True)
        # MPDS phase id
        spec.input('mpds_query', valid_type=get_data_class('dict'), required=True)
        # Basis
        spec.expose_inputs(BaseCrystalWorkChain, include=['basis_family'])
        # Parameters (include OPTGEOM, FREQCALC and ELASTCON)
        spec.input('crystal_parameters', valid_type=get_data_class('dict'), required=True)
        spec.input('properties_parameters', valid_type=get_data_class('dict'), required=True)
        spec.input('options', valid_type=get_data_class('dict'), required=True, help="Calculation options")
        # define workchain routine
        spec.outline(cls.init_inputs,
                     cls.validate_inputs,
                     cls.optimize_geometry,
                     cls.calculate_phonons,
                     cls.calculate_elastic_constants,
                     cls.run_properties_calc,
                     cls.retrieve_results)
        # define outputs
        spec.output('phonons_parameters', valid_type=get_data_class('dict'), required=False)
        spec.output('elastic_parameters', valid_type=get_data_class('dict'), required=False)
        spec.expose_outputs(BaseCrystalWorkChain)
        spec.expose_outputs(BasePropertiesWorkChain)

    def init_inputs(self):
        self.ctx.inputs = AttributeDict()
        self.ctx.inputs.crystal = AttributeDict()
        self.ctx.inputs.properties = AttributeDict()
        # set the crystal workchain inputs; structure is found by get_structure
        self.ctx.inputs.crystal.code = self.inputs.crystal_code
        self.ctx.inputs.crystal.basis_family = self.inputs.basis_family
        self.ctx.inputs.crystal.structure = self.get_geometry()
        # set the properties workchain   inputs
        self.ctx.inputs.properties.code = self.inputs.properties_code
        self.ctx.inputs.properties.parameters = self.inputs.properties_parameters
        # properties wavefunction input must be set after crystal run
        options_dict = self.inputs.options.get_dict()
        self.ctx.need_phonons = options_dict.get('need_phonons', self.DEFAULT['need_phonons'])
        self.ctx.need_elastic_constants = options_dict.get('need_elastic', self.DEFAULT['need_elastic_constants'])
        self.ctx.need_electronic_properties = options_dict.get('need_properties',
                                                               self.DEFAULT['need_electronic_properties'])

    def get_geometry(self):
        """Getting geometry from MPDS database"""
        key = os.getenv('MPDS_KEY')
        client = MPDSDataRetrieval(api_key=key)
        query_dict = self.inputs.mpds_query.get_dict()
        # insert props: atomic structure to query. Might check if it's already set to smth
        query_dict['props'] = 'atomic structure'
        answer = client.get_data(
            query_dict,
            fields={'S': [
                'cell_abc',
                'sg_n',
                'basis_noneq',
                'els_noneq'
            ]}
        )
        structs = [client.compile_crystal(line, flavor='ase') for line in answer]
        minimal_struct = min([len(s) for s in structs])
        # get structures with minimal number of atoms and find the one with median cell vectors
        cells = np.array([s.get_cell().reshape(9) for s in structs if len(s) == minimal_struct])
        median_cell = np.median(cells, axis=0)
        median_idx = int(np.argmin(np.sum((cells - median_cell) ** 2, axis=1) ** 0.5))
        return get_data_class('structure')(ase=structs[median_idx])

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
        # remove unneeded
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

    def optimize_geometry(self):
        self.ctx.inputs.crystal.parameters = get_data_class('dict')(dict=self.ctx.crystal_parameters.optimise)
        self.ctx.inputs.crystal.options = get_data_class('dict')(dict=self.construct_metadata('Geometry optimization'))
        crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
        return self.to_context(optimise=crystal_run)

    def calculate_phonons(self):
        if self.ctx.need_phonons:
            # run phonons with optimised structure
            self.ctx.inputs.crystal.structure = self.ctx.optimise.outputs.output_structure
            self.ctx.inputs.crystal.parameters = get_data_class('dict')(dict=self.ctx.crystal_parameters.phonons)
            self.ctx.inputs.crystal.options = get_data_class('dict')(
                dict=self.construct_metadata('Phonon frequency'))
            crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
            return self.to_context(phonons=crystal_run)
        else:
            self.logger.warning("Skipping phonon frequency calculation")

    def calculate_elastic_constants(self):
        if self.ctx.need_elastic_constants:
            # run elastic calc with optimised structure
            self.ctx.inputs.crystal.structure = self.ctx.optimise.outputs.output_structure
            self.ctx.inputs.crystal.parameters = get_data_class('dict')(
                dict=self.ctx.crystal_parameters.elastic_constants)
            self.ctx.inputs.crystal.options = get_data_class('dict')(
                dict=self.construct_metadata('Elastic constants'))
            crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
            return self.to_context(elastic_constants=crystal_run)
        else:
            self.logger.warning("Skipping elastic constants calculation")

    def run_properties_calc(self):
        if self.ctx.need_electronic_properties:
            self.ctx.inputs.properties.wavefunction = self.ctx.optimise.outputs.output_wavefunction
            self.ctx.inputs.properties.options = get_data_class('dict')(
                dict=self.construct_metadata('One-electron properties'))
            properties_run = self.submit(BasePropertiesWorkChain, **self.ctx.inputs.properties)
            return self.to_context(properties=properties_run)
        else:
            self.logger.warning("Skipping one-electron properties calculation")

    def retrieve_results(self):
        # expose all outputs of optimized structure and properties calcs
        self.out_many(self.exposed_outputs(self.ctx.optimise, BaseCrystalWorkChain))
        if self.ctx.need_phonons:
            self.out('phonons_parameters', self.ctx.phonons.outputs.output_parameters)
        if self.ctx.need_elastic_constants:
            self.out('elastic_parameters', self.ctx.elastic_constants.outputs.output_parameters)
        if self.ctx.need_electronic_properties:
            self.out_many(self.exposed_outputs(self.ctx.properties, BasePropertiesWorkChain))