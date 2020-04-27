"""
The workflow for AiiDA combining CRYSTAL and MPDS
"""
import os
import time
import random

import numpy as np
from mpds_client import MPDSDataRetrieval, APIError

from aiida.engine import WorkChain, if_
from aiida.orm import Code
from aiida.common.extendeddicts import AttributeDict
from aiida_crystal_dft.utils import get_data_class
from aiida_crystal_dft.workflows.base import BaseCrystalWorkChain, BasePropertiesWorkChain
from . import GEOMETRY_LABEL, PHONON_LABEL, ELASTIC_LABEL, PROPERTIES_LABEL


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
        spec.input('properties_code', valid_type=Code, required=False)

        # MPDS phase id
        spec.input('mpds_query', valid_type=get_data_class('dict'), required=True)
        # Add direct structures submitting support: FIXME
        spec.input('struct_in', valid_type=get_data_class('structure'), required=False)

        # Basis set
        spec.expose_inputs(BaseCrystalWorkChain, include=['basis_family'])

        # Parameters (include OPTGEOM, FREQCALC and ELASTCON)
        spec.input('crystal_parameters', valid_type=get_data_class('dict'), required=True)
        spec.input('properties_parameters', valid_type=get_data_class('dict'), required=False)
        spec.input('options', valid_type=get_data_class('dict'), required=True, help="Calculation options")

        # define workchain routine
        spec.outline(cls.init_inputs,
                     cls.validate_inputs,
                     cls.optimize_geometry,
                     if_(cls.needs_phonons)(
                         cls.calculate_phonons),
                     cls.calculate_elastic_constants,
                     if_(cls.needs_properties_run)(
                         cls.run_properties_calc),
                     cls.retrieve_results)

        # define outputs
        spec.output('phonons_parameters', valid_type=get_data_class('dict'), required=False)
        spec.output('elastic_parameters', valid_type=get_data_class('dict'), required=False)
        spec.expose_outputs(BaseCrystalWorkChain)
        spec.expose_outputs(BasePropertiesWorkChain)

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
        self.ctx.inputs = AttributeDict()
        self.ctx.inputs.crystal = AttributeDict()
        self.ctx.inputs.properties = AttributeDict()

        # set the crystal workchain inputs; structure is found by get_structure
        self.ctx.inputs.crystal.code = self.inputs.crystal_code
        self.ctx.inputs.crystal.basis_family = self.inputs.basis_family
        self.ctx.inputs.crystal.structure = self.get_geometry()

        # set the properties workchain inputs
        self.ctx.inputs.properties.code = self.inputs.get('properties_code', None)
        self.ctx.inputs.properties.parameters = self.inputs.get('properties_parameters', None)

        # properties wavefunction input must be set after crystal run
        options_dict = self.inputs.options.get_dict()
        self.ctx.need_elastic_constants = options_dict.get('need_elastic_constants',
                                                           self.DEFAULT['need_elastic_constants'])

    def get_geometry(self):
        """ Getting geometry from MPDS database
        """
        key = os.getenv('MPDS_KEY')
        client = MPDSDataRetrieval(api_key=key, verbose=False)
        query_dict = self.inputs.mpds_query.get_dict()

        # Add direct structures submitting support: FIXME
        assert query_dict or self.inputs.struct_in
        if not query_dict:
            return self.inputs.struct_in

        # insert props: atomic structure to query. Might check if it's already set to smth
        query_dict['props'] = 'atomic structure'
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
            else: raise

        structs = [client.compile_crystal(line, flavor='ase') for line in answer]
        structs = list(filter(None, structs))
        if not structs:
            raise APIError('No crystal structures returned')
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
        self.ctx.inputs.crystal.options = get_data_class('dict')(dict=self.construct_metadata(GEOMETRY_LABEL))
        crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
        return self.to_context(optimise=crystal_run)

    def calculate_phonons(self):
        self.ctx.inputs.crystal.structure = self.ctx.optimise.outputs.output_structure
        self.ctx.inputs.crystal.parameters = get_data_class('dict')(dict=self.ctx.crystal_parameters.phonons)
        self.ctx.inputs.crystal.options = get_data_class('dict')(
            dict=self.construct_metadata(PHONON_LABEL))
        crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
        return self.to_context(phonons=crystal_run)

    def calculate_elastic_constants(self):
        if self.ctx.need_elastic_constants:
            # run elastic calc with optimised structure
            self.ctx.inputs.crystal.structure = self.ctx.optimise.outputs.output_structure
            self.ctx.inputs.crystal.parameters = get_data_class('dict')(
                dict=self.ctx.crystal_parameters.elastic_constants)
            self.ctx.inputs.crystal.options = get_data_class('dict')(
                dict=self.construct_metadata(ELASTIC_LABEL))
            crystal_run = self.submit(BaseCrystalWorkChain, **self.ctx.inputs.crystal)
            return self.to_context(elastic_constants=crystal_run)

        else:
            self.logger.warning("Skipping elastic constants calculation")

    def run_properties_calc(self):
        self.ctx.inputs.properties.wavefunction = self.ctx.optimise.outputs.output_wavefunction
        self.ctx.inputs.properties.options = get_data_class('dict')(
            dict=self.construct_metadata(PROPERTIES_LABEL))
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
