"""
WorkChain that orchestrates CRYSTAL optimization followed by Seebeck properties calculation.
"""
import tempfile

from aiida.engine import WorkChain, if_, ToContext
from aiida.orm import Code, SinglefileData, StructureData
from aiida.orm.nodes.data.base import to_aiida_type
from aiida_crystal_dft.utils import get_data_class
from aiida_crystal_dft.workflows.base import BaseCrystalWorkChain, BasePropertiesWorkChain

from .mpds import MPDSStructureWorkChain
from .aiida import AiidaStructureWorkChain
from .properties import CustomPropertiesWorkChain


class MPDSCrystalSeebeckWorkChain(WorkChain):

    CRYSTAL_EXIT_CODE_MAP = {
        410: 'INPUT_ERROR',
        411: 'ERROR_INVALID_CODE',
        412: 'ERROR_OPTIMIZATION_FAILED',
    }

    @classmethod
    def define(cls, spec):
        super().define(spec)

        spec.input('workchain_options',
                   valid_type=get_data_class('dict'),
                   required=False,
                   default=lambda: get_data_class('dict')(dict={}),
                   help="Calculation options forwarded to the crystal WorkChain",
                   serializer=to_aiida_type)
        spec.input('mpds_query',
                   valid_type=get_data_class('dict'),
                   required=False,
                   help="MPDS query dict; if provided, MPDSStructureWorkChain is used")
        spec.input('structure',
                   valid_type=StructureData,
                   required=False,
                   help="AiiDA StructureData; if provided (without mpds_query), AiidaStructureWorkChain is used")
        spec.input('check_for_bond_type',
                   valid_type=get_data_class('bool'),
                   required=False,
                   default=lambda: get_data_class('bool')(True),
                   help="Forwarded to the crystal WorkChain",
                   serializer=to_aiida_type)
        spec.input('properties_code',
                   valid_type=Code,
                   required=True,
                   help="CRYSTAL Properties code for the Seebeck calculation")
        spec.input('properties_parameters',
                   valid_type=get_data_class('dict'),
                   required=False,
                   help="Parameters forwarded to the properties WorkChain",
                   serializer=to_aiida_type)
        spec.input('properties_options',
                   valid_type=get_data_class('dict'),
                   required=False,
                   help="Options forwarded to the properties WorkChain",
                   serializer=to_aiida_type)

        spec.outline(
            cls.run_crystal,
            cls.check_crystal,
            if_(cls.should_run_properties)(
                cls.run_properties,
                cls.finalize_properties,
            ),
        )

        spec.expose_outputs(BaseCrystalWorkChain, exclude=('output_parameters',), namespace='crystal')
        spec.expose_outputs(CustomPropertiesWorkChain, namespace='properties')
        spec.output_namespace('crystal.output_parameters', valid_type=get_data_class('dict'), required=False, dynamic=True)

        spec.exit_code(410, 'INPUT_ERROR', 'Invalid or conflicting inputs')
        spec.exit_code(450, 'ERROR_CRYSTAL_FAILED', 'The crystal WorkChain did not finish OK')
        spec.exit_code(411, 'ERROR_INVALID_CODE', 'Non-existent code is given')
        spec.exit_code(412, 'ERROR_OPTIMIZATION_FAILED', 'Structure optimization failed')
        spec.exit_code(451, 'ERROR_PROPERTIES_FAILED', 'The properties WorkChain did not finish OK')

    def run_crystal(self):
        has_mpds = 'mpds_query' in self.inputs
        has_structure = 'structure' in self.inputs and self.inputs.structure is not None

        if has_mpds and has_structure:
            self.report("Both mpds_query and structure provided; exactly one must be given")
            return self.exit_codes.INPUT_ERROR
        if not has_mpds and not has_structure:
            self.report("Neither mpds_query nor structure provided; exactly one must be given")
            return self.exit_codes.INPUT_ERROR

        if has_mpds:
            self.report("Using MPDSStructureWorkChain for crystal step")
            crystal_class = MPDSStructureWorkChain
        else:
            self.report("Using AiidaStructureWorkChain for crystal step")
            crystal_class = AiidaStructureWorkChain

        inputs = {
            'workchain_options': self.inputs.workchain_options,
            'check_for_bond_type': self.inputs.check_for_bond_type,
        }
        if has_mpds:
            inputs['mpds_query'] = self.inputs.mpds_query
        else:
            inputs['structure'] = self.inputs.structure
        inputs['metadata'] = {'label': 'CRYSTAL optimization step'}

        running = self.submit(crystal_class, **inputs)
        return ToContext(crystal=running)

    def check_crystal(self):
        crystal = self.ctx.crystal

        if crystal.is_finished_ok:
            self._expose_crystal_outputs(crystal)

            wavefunction = self._extract_wavefunction(crystal)
            if wavefunction is None:
                self.report("Crystal step finished OK but no wavefunction found")
                self.ctx.ready_for_properties = False
                return self.exit_codes.ERROR_CRYSTAL_FAILED

            self.ctx.wavefunction = wavefunction
            self.ctx.ready_for_properties = True
            self.report("Crystal step finished OK, wavefunction extracted")
            return

        exit_status = crystal.exit_status
        if exit_status in self.CRYSTAL_EXIT_CODE_MAP:
            self.report(f"Crystal step failed with exit code {exit_status}: {self.CRYSTAL_EXIT_CODE_MAP[exit_status]}")
            self.ctx.ready_for_properties = False
            return self.exit_codes[self.CRYSTAL_EXIT_CODE_MAP[exit_status]]

        self.report(f"Crystal step failed with exit status {exit_status}")
        self.ctx.ready_for_properties = False
        return self.exit_codes.ERROR_CRYSTAL_FAILED

    def should_run_properties(self):
        return getattr(self.ctx, 'ready_for_properties', False)

    def run_properties(self):
        self.report("Launching CustomPropertiesWorkChain for Seebeck calculation")

        default_resources = {
            'num_machines': 1,
            'num_mpiprocs_per_machine': 1,
        }
        default_options = {
            'resources': default_resources,
            'max_wallclock_seconds': 3600,
        }

        if 'properties_options' in self.inputs:
            options_node = self.inputs.properties_options
        else:
            options_node = get_data_class('dict')(dict=default_options)

        if 'properties_parameters' in self.inputs:
            params_node = self.inputs.properties_parameters
        else:
            params_node = get_data_class('dict')(dict={
                'newk': {'k_points': [8, 8], 'fermi': True},
                'boltztra': {
                    'trange': [300, 800, 50],
                    'murange': [-0.15, 0.15, 0.001],
                    'tdfrange': [-0.15, 0.15, 0.001],
                    'relaxtim': 10,
                },
            })

        inputs = {
            'code': self.inputs.properties_code,
            'wavefunction': self.ctx.wavefunction,
            'parameters': params_node,
            'options': options_node,
        }

        running = self.submit(CustomPropertiesWorkChain, **inputs)
        return ToContext(properties=running)

    def finalize_properties(self):
        props = self.ctx.properties
        if not props.is_finished_ok:
            self.report(f"Properties step failed with exit status {props.exit_status}")
            return self.exit_codes.ERROR_PROPERTIES_FAILED

        self.out_many(self.exposed_outputs(props, CustomPropertiesWorkChain, namespace='properties'))
        self.report("Pipeline completed: crystal optimization + Seebeck properties")

    def _expose_crystal_outputs(self, crystal):
        self.out_many(self.exposed_outputs(crystal, BaseCrystalWorkChain, namespace='crystal'))
        try:
            for key in crystal.outputs.output_parameters.keys():
                self.out(f'crystal.output_parameters.{key}', crystal.outputs.output_parameters[key])
        except (AttributeError, TypeError):
            pass

    def _extract_wavefunction(self, crystal_workchain):
        for called in crystal_workchain.called:
            if not hasattr(called, 'outputs'):
                continue
            if hasattr(called.outputs, 'retrieved'):
                retrieved = called.outputs.retrieved
                if 'fort.9' in retrieved.list_object_names():
                    with retrieved.open('fort.9', mode='rb') as f:
                        content = f.read()
                    with tempfile.NamedTemporaryFile(suffix='.fort9') as tmp:
                        tmp.write(content)
                        tmp.flush()
                        sfd = SinglefileData(tmp.name, filename='fort.9').store()
                        self.report(f"Extracted fort.9 as SinglefileData PK={sfd.pk}")
                        return sfd
            if hasattr(called, 'called'):
                result = self._extract_wavefunction(called)
                if result is not None:
                    return result
        return None