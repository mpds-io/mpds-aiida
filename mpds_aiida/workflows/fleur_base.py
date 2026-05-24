from copy import deepcopy

from aiida.engine import ExitCode, ToContext, WorkChain, if_
from aiida.orm import Dict, StructureData, Str, Int, List, load_node, load_code
from aiida.plugins import WorkflowFactory
from aiida_crystal_dft.utils import recursive_update

from ..common import get_initial_parameters_from_structure, get_template
from .fleur_phonopy import PhonopyFleurWorkChain

OPTIMIZERS = {
    "scf": {
        "Adam": "reoptimize.AdamFleurSCFOptimizer",
        "RMSprop": "reoptimize.RMSpropFleurSCFOptimizer",
        "BFGS": "reoptimize.BFGSFleurSCFOptimizer",
        "CG": "reoptimize.CDGFleurSCFOptimizer",
    },
    "relax": {
        "Adam": "reoptimize.AdamFleurRelaxOptimizer",
        "RMSprop": "reoptimize.RMSpropFleurRelaxOptimizer",
        "BFGS": "reoptimize.BFGSFleurRelaxOptimizer",
        "CG": "reoptimize.CDGFleurRelaxOptimizer",
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
            default=lambda: Str("flapw_default.yml"),
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
            cls.inspect_optimization,
            if_(cls.need_phonons)(  # ty:ignore[invalid-argument-type]
                cls.run_phonons,
                cls.inspect_phonons,
            ),
        )
        spec.exit_code(
            412,
            "ERROR_OPTIMIZATION_FAILED",
            message="Structure optimization failed",
        )
        spec.exit_code(
            413,
            "ERROR_PHONONS_FAILED",
            message="Phonon calculation failed",
        )
        spec.exit_code(
            414,
            "ERROR_TRANSPORT_FAILED",
            message="Transport properties calculation failed",
        )
        spec.output("optimized_structure", valid_type=StructureData, required=False)
        spec.output("phonon_results", valid_type=Dict, required=False)
        spec.output("transport_results", valid_type=Dict, required=False)

    def init_inputs(self):
        config_path = self.inputs.config_file.value
        try:
            options = get_template(config_path)
        except Exception:
            raise FileNotFoundError(f"Config file '{config_path}' not found")

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
        self.ctx.optimizer_name = options["options"].get("optimizer", "Adam")

        # Auto-detect initial parameters
        ase_struct = self.ctx.structure.get_ase()
        params, _ = get_initial_parameters_from_structure(ase_struct)
        self.ctx.initial_parameters = params

    def need_phonons(self):
        return self.ctx.need_phonons and self.ctx.optimize

    # TODO Сделать так чтобы параметры можно было перезаписывать из внешнего инпута
    def run_optimization(self):
        if not self.ctx.optimize:
            self.ctx.optimized_structure = self.ctx.structure
            return

        optimizer_wc = self.get_optimizer(
            self.ctx.optimizer_name, self.ctx.calculator_type
        )

        # Prepearing to start calcs
        calc_params = deepcopy(self.ctx.config["default"][self.ctx.calculator_type])
        calc_params.update(
            {
                "codes": {
                    "fleur": self.ctx.codes["fleur"],
                    "inpgen": self.ctx.codes["inpgen"],
                }
            }
        )

        # algorithm_settings from config
        algo_settings = (
            self.ctx.config.get("calculations", {})
            .get("optimize", {})
            .get("parameters", {})
            .get("algorithm_settings", {})
        )

        optimizer_inputs = {
            "structure": self.ctx.structure,
            "itmax": self.ctx.config.get("itmax", Int(100)),
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

        future = self.submit(optimizer_wc, **optimizer_inputs)  # ty:ignore[invalid-argument-type]
        return ToContext(optimization=future)

    def inspect_optimization(self):
        if not self.ctx.optimize:
            self.out("optimized_structure", self.ctx.optimized_structure)
            return

        opt_workchain = self.ctx.optimization
        if not opt_workchain.is_finished_ok:
            return self._child_exit_code(
                opt_workchain,
                "Optimization",
                self.exit_codes.ERROR_OPTIMIZATION_FAILED,
            )

        try:
            best_pk = opt_workchain.outputs.result_node_pk.value
            best_calc = load_node(best_pk)
            optimized_structure = best_calc.inputs.structure
        except Exception as exc:
            self.report(f"Could not extract optimized structure: {exc}")
            return self.exit_codes.ERROR_OPTIMIZATION_FAILED

        self.ctx.optimized_structure = optimized_structure
        self.out("optimized_structure", optimized_structure)

    def run_phonons(self):
        optimized_structure = self.ctx.optimized_structure

        phonon_params = self.ctx.config["calculations"]["phonons"]["parameters"]

        phonopy_parameters = {
            key.upper(): value
            for key, value in phonon_params.get(
                "phonopy_parameters", {"WRITE_FORCE_CONSTANTS": True}
            ).items()
        }

        phonon_inputs = {
            "structure": optimized_structure,
            "supercell_matrix": List(list=phonon_params["supercell_matrix"]),
            "fleur_parameters": Dict(
                dict={
                    "fleur": self.ctx.codes["fleur"],
                    **self.ctx.config["default"]["scf"],
                }
            ),
            "phonopy": {
                "code": load_code(self.ctx.codes["phonopy"]),
                "parameters": Dict(dict=phonopy_parameters),
            },
        }

        # TODO make label style exactly match MPDSStructureWorkChain
        label = f"{self.ctx.phase_label} - phonons"
        phonon_inputs["metadata"] = {"label": label}

        future = self.submit(PhonopyFleurWorkChain, **phonon_inputs)  # ty:ignore[invalid-argument-type]
        return ToContext(phonons=future)

    def inspect_phonons(self):
        phonon_workchain = self.ctx.phonons
        if not phonon_workchain.is_finished_ok:
            return self._child_exit_code(
                phonon_workchain,
                "Phonon calculation",
                self.exit_codes.ERROR_PHONONS_FAILED,
            )

        if "phonon_results" in phonon_workchain.outputs:
            self.out("phonon_results", phonon_workchain.outputs.phonon_results)

    def inspect_transport(self):
        transport_workchain = self.ctx.transport
        if not transport_workchain.is_finished_ok:
            return self._child_exit_code(
                transport_workchain,
                "Transport properties calculation",
                self.exit_codes.ERROR_TRANSPORT_FAILED,
            )

        if "output_dos_local_wc_para" in transport_workchain.outputs:
            self.out(
                "transport_results",
                transport_workchain.outputs.output_dos_local_wc_para,
            )

    def _child_exit_code(self, process, calculation_label, fallback):
        details = []
        exit_status = getattr(process, "exit_status", None)
        exit_message = getattr(process, "exit_message", None)

        if exit_status is not None:
            details.append(f"exit status {exit_status}")
        if exit_message:
            details.append(f"exit message: {exit_message}")

        exception = getattr(process, "exception", None)
        if exception:
            details.append(f"exception: {exception}")

        message = f"{calculation_label} failed"
        if details:
            message = f"{message} ({'; '.join(details)})"
        self.report(message)

        if exit_status is not None:
            return ExitCode(
                status=exit_status,
                message=exit_message or fallback.message,
            )

        return fallback

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
            self.report(
                f"Invalid optimizer {optimizer_type} or calculation type {calculation_type}"
            )
            return WorkflowFactory(
                OPTIMIZERS[calculation_type]["BFGS"]
            )  # fallback to BFGS
