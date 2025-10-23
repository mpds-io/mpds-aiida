import os
from copy import deepcopy

from aiida.engine import ToContext, WorkChain, if_
from aiida.orm import Dict, StructureData, load_code, load_node
from aiida.plugins import WorkflowFactory
from aiida_crystal_dft.utils import recursive_update

from ..common import get_initial_parameters_from_structure, get_template
from .phonopy_fleur import PhonopyFleurWorkChain

# TODO turn it into a nested dict
# TODO Fix issues with CG optimizer
OPTIMIZERS_SCF = {
    "Adam": "aiida_reoptimize.AdamFleurSCFOptimizer",
    "RMSprop": "aiida_reoptimize.RMSpropFleurSCFOptimizer",
    # "CG": "aiida_reoptimize.CDGFleurSCFOptimizer",
    "BFGS": "aiida_reoptimize.BFGSFleurSCFOptimizer",
}

OPTIMIZERS_RELAX = {
    "Adam": "aiida_reoptimize.AdamFleurRelaxOptimizer",
    "RMSprop": "aiida_reoptimize.RMSpropFleurRelaxOptimizer",
    # "CG": "aiida_reoptimize.CDGFleurRelaxOptimizer",
    "BFGS": "aiida_reoptimize.BFGSFleurRelaxOptimizer",
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
            valid_type=str,
            required=False,
            default="fleur_default.yml",
        )
        spec.input(
            "phase_label",
            valid_type=str,
            required=False,
            default="unknown_phase",
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
        config_path = self.inputs.config_file
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file {config_path} not found")

        options = get_template(config_path)
        user_opts = self.inputs.workchain_options.get_dict()
        if user_opts:
            recursive_update(options, user_opts)

        self.ctx.config = options
        self.ctx.structure = self.inputs.structure
        self.ctx.phase_label = self.inputs.phase_label

        # Load codes
        self.ctx.codes = {}
        for name, label in options["codes"].items():
            self.ctx.codes[name] = load_code(label)

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

        # TODO make optimizer selection more flexible
        if self.ctx.calculator_type == "scf":
            opt_map = OPTIMIZERS_SCF
        elif self.ctx.calculator_type == "relax":
            opt_map = OPTIMIZERS_RELAX
        else:
            raise ValueError(
                f"Unsupported calculator type: {self.ctx.calculator_type}"
            )

        if self.ctx.optimizer_name not in opt_map:
            raise ValueError(
                f"Optimizer {self.ctx.optimizer_name} not supported for {self.ctx.calculator_type}"
            )

        optimizer_wc = WorkflowFactory(opt_map[self.ctx.optimizer_name])

        # Prepearing to start calcs
        calc_params = deepcopy(
            self.ctx.config["default"][self.ctx.calculator_type]
        )
        calc_params.update({
            "fleur": self.ctx.codes["fleur"],
            "inpgen": self.ctx.codes["inpgen"],
        })

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
