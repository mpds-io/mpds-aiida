from copy import deepcopy

from aiida.engine import ToContext, WorkChain, if_
from aiida.orm import Dict, StructureData, Str, load_node
from aiida.plugins import WorkflowFactory
from aiida_crystal_dft.utils import recursive_update

from ..common import get_initial_parameters_from_structure, get_template
from .phonopy_fleur import PhonopyFleurWorkChain

OPTIMIZERS = {
    "scf": {
        "Adam": "aiida_reoptimize.AdamFleurSCFOptimizer",
        "RMSprop": "aiida_reoptimize.RMSpropFleurSCFOptimizer",
        "BFGS": "aiida_reoptimize.BFGSFleurSCFOptimizer",
        "CG": "aiida_reoptimize.CGFleurSCFOptimizer",
    },
    "relax": {
        "Adam": "aiida_reoptimize.AdamFleurRelaxOptimizer",
        "RMSprop": "aiida_reoptimize.RMSpropFleurRelaxOptimizer",
        "BFGS": "aiida_reoptimize.BFGSFleurRelaxOptimizer",
        "CG": "aiida_reoptimize.CGFleurRelaxOptimizer",
    },
}


class MPDSFleurWorkChain(WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("structure", valid_type=StructureData, required=True)
        spec.input(
            "workchain_options",
            valid_type=Dict,
            required=False,
            default=lambda: Dict(dict={}),
        )
        spec.input(
            "config_file",
            valid_type=Str,
            required=False,
            default=lambda: Str("fleur_default.yml"),
        )
        spec.input(
            "phase_label",
            valid_type=Str,
            required=False,
            default=lambda: Str("unknown_phase"),
        )

        spec.outline(
            cls.init_inputs,
            cls.run_optimization,
            if_(cls.need_phonons)(cls.run_phonons),
        )
        spec.output(
            "optimized_structure", valid_type=StructureData, required=False
        )
        spec.output("phonon_results", valid_type=Dict, required=False)

    def init_inputs(self):
        config_path = self.inputs.config_file.value
        try:
            options = get_template(config_path)
        except Exception:
            raise FileNotFoundError(
                f"Config file '{config_path}' not found"
            )

        user_opts = self.inputs.workchain_options.get_dict()
        if user_opts:
            recursive_update(options, user_opts)

        self.ctx.config = options
        self.ctx.structure = self.inputs.structure
        self.ctx.phase_label = self.inputs.phase_label.value

        # Just sends codes labels, optimizer must load them, 
        # since loaded_code is not serializable
        self.ctx.codes = {}
        for name, label in options["codes"].items():
            self.ctx.codes[name] = label

        # Flags
        self.ctx.need_phonons = options["options"].get("need_phonons", False)
        self.ctx.optimize = options["options"].get("optimize_structure", True)
        self.ctx.calculator_type = options["options"].get("calculator", "scf")
        self.ctx.optimizer_name = options["options"].get("optimizer", "BFGS")

        # Auto-detect initial parameters
        ase_struct = self.ctx.structure.get_ase()
        params, _ = get_initial_parameters_from_structure(ase_struct)
        self.ctx.initial_parameters = params

    def need_phonons(self):
        return self.ctx.need_phonons and self.ctx.optimize

    def run_optimization(self):
        if not self.ctx.optimize:
            self.ctx.optimized_structure = self.ctx.structure
            return

        optimizer_wc = self.get_optimizer(self.ctx.optimizer_name, self.ctx.calculator_type)

        # Prepearing to start calcs
        calc_params = deepcopy(
            self.ctx.config["default"][self.ctx.calculator_type]
        )
        calc_params.update({"codes":{
            "fleur": self.ctx.codes["fleur"],
            "inpgen": self.ctx.codes["inpgen"],
        }})

        # algorithm_settings from config
        algo_settings = (
            self.ctx.config.get("calculations", {})
            .get("optimize", {})
            .get("parameters", {})
            .get("algorithm_settings", {})
        )

        optimizer_inputs = {
            "structure": self.ctx.structure,
            # TODO Move it to config
            "itmax": self.inputs.workchain_options.get("itmax", 50),
            "parameters": Dict(
                dict={
                    "initial_parameters": self.ctx.initial_parameters,
                    "algorithm_settings": algo_settings,
                    "calculator_parameters": calc_params,
                }
            ),
            "get_best": True,
        }

        # TODO make label style exactly match MPDSStructureWorkChain
        label = f"{self.ctx.phase_label} - optimization"
        optimizer_inputs["metadata"] = {"label": label}

        future = self.submit(optimizer_wc, **optimizer_inputs)
        return ToContext(optimization=future)

    def run_phonons(self):
        opt_workchain = self.ctx.optimization
        if not opt_workchain.is_finished_ok:
            self.report("Optimization failed, skipping phonons")
            return

        best_pk = opt_workchain.outputs.result_node_pk.value

        best_calc = load_node(best_pk)
        optimized_structure = best_calc.inputs.structure

        phonon_params = self.ctx.config["calculations"]["phonons"][
            "parameters"
        ]

        # TODO DOUBLECHECK THIS SECTION EXTRA CAREFULLY
        phonon_inputs = {
            "structure": optimized_structure,
            "fleur_parameters": Dict(
                dict={
                    "fleur": self.ctx.codes["fleur"],
                    "inpgen": self.ctx.codes["inpgen"],
                    **self.ctx.config["default"]["scf"],
                }
            ),
            "phonopy_parameters": Dict(
                dict={
                    "supercell_matrix": phonon_params["supercell_matrix"],
                    "distance": phonon_params["displacement_distance"],
                }
            ),
        }

        # TODO make label style exactly match MPDSStructureWorkChain
        label = f"{self.ctx.phase_label} - phonons"
        phonon_inputs["metadata"] = {"label": label}

        future = self.submit(PhonopyFleurWorkChain, **phonon_inputs)
        return ToContext(phonons=future)

    def get_optimizer(self, optimizer_type: str, calculation_type: str):
        """
        Get optimizer class with proper error handling.

        Args:
            optimizer_type (str): Type of optimizer (Adam, RMSprop, BFGS, CG)
            calculation_type (str): Type of calculation (scf, relax)

        Returns:
            WorkflowFactory: Optimizer workflow factory
        """
        try:
            optimizer_path = OPTIMIZERS[calculation_type][optimizer_type]
            return WorkflowFactory(optimizer_path)
        except KeyError:
            self.report(f"Invalid optimizer {optimizer_type} or calculation type {calculation_type}")
            return WorkflowFactory(OPTIMIZERS[calculation_type]["BFGS"])  # fallback to BFGS
