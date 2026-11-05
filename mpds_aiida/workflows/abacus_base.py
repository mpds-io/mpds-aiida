from copy import deepcopy

from aiida.engine import ExitCode, ToContext, WorkChain, if_
from aiida.orm import (
    Bool,
    Dict,
    Float,
    Int,
    KpointsData,
    List,
    Str,
    StructureData,
    load_code,
)
from aiida_abacus.workflows.base import AbacusBaseWorkChain
from aiida_abacus.workflows.relax import AbacusRelaxWorkChain
from aiida_crystal_dft.utils import recursive_update

from ..abacus_forces import read_scf_log, scf_has_converged
from ..common import get_template
from .abacus_phonopy import PhonopyAbacusWorkChain


class MPDSAbacusWorkChain(WorkChain):
    """
    ABACUS engine chain: (optional) structure optimization followed by
    frozen phonons, configured via a calc template like abacus_default.yml.
    """

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
            default=lambda: Str("abacus_default.yml"),
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
            if_(cls.need_scf)(cls.run_scf, cls.inspect_scf),
            if_(cls.need_phonons)(
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
        spec.exit_code(414, "ERROR_SCF_FAILED", message="SCF calculation failed")
        spec.exit_code(
            415,
            "ERROR_SCF_NOT_CONVERGED",
            message="SCF convergence could not be verified",
        )
        spec.output("output_scf", valid_type=Dict, required=False)
        spec.output("optimized_structure", valid_type=StructureData, required=False)
        spec.output("output_phonopy", valid_type=Dict, required=False)

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

        # Just sends code labels, sub workchains must load them,
        # since loaded_code is not serializable
        self.ctx.codes = {}
        for name, label in options["codes"].items():
            self.ctx.codes[name] = label

        # Flags
        engine_options = options["options"]
        self.ctx.need_phonons = engine_options.get("need_phonons", False)
        self.ctx.optimize = engine_options.get("optimize_structure", True)
        self.ctx.calculation = engine_options.get("calculation", "cell-relax")
        self.ctx.options_run = engine_options.get("run", {})

    def need_phonons(self):
        return self.ctx.need_phonons

    def need_scf(self):
        return self.ctx.calculation == "scf" and not self.ctx.need_phonons

    def run_scf(self):
        options = self.ctx.config["options"]
        parameters = deepcopy(
            self.ctx.config.get("default", {}).get("scf", {}).get("input", {})
        )
        parameters["calculation"] = "scf"
        builder = AbacusBaseWorkChain.get_builder()
        builder.abacus.code = load_code(self.ctx.codes["abacus"])
        builder.abacus.structure = self.ctx.structure
        builder.abacus.parameters = Dict(dict={"input": parameters})
        if "yascheduler" in self.ctx.codes["abacus"]:
            builder.abacus.settings = Dict(dict={"flat_output": True})
        kpoints = KpointsData()
        kpoints.set_cell_from_structure(self.ctx.structure)
        kpoints.set_kpoints_mesh(list(options.get("kpoints", [4, 4, 4])))
        builder.kpoints = kpoints
        if options.get("pseudo_family"):
            builder.pseudo_family = Str(options["pseudo_family"])
        builder.abacus.metadata.options = self.ctx.options_run
        builder.metadata.label = f"{self.ctx.phase_label} - scf"
        return ToContext(scf=self.submit(builder))

    def inspect_scf(self):
        scf = self.ctx.scf
        if not scf.is_finished_ok:
            return self.exit_codes.ERROR_SCF_FAILED
        try:
            converged = scf_has_converged(read_scf_log(scf.outputs.misc.creator))
        except (AttributeError, KeyError, OSError, ValueError) as exc:
            self.report(f"Cannot verify SCF convergence: {exc}")
            return self.exit_codes.ERROR_SCF_NOT_CONVERGED
        if not converged:
            return self.exit_codes.ERROR_SCF_NOT_CONVERGED
        self.out("output_scf", scf.outputs.misc)

    def run_optimization(self):
        if not self.ctx.optimize or self.ctx.calculation == "scf":
            if self.ctx.optimize and self.ctx.calculation == "scf":
                self.report("calculation is set to 'scf', skipping optimization")
            self.ctx.optimized_structure = self.ctx.structure
            return

        engine_options = self.ctx.config["options"]
        scf_input = deepcopy(
            self.ctx.config.get("default", {}).get("scf", {}).get("input", {})
        )
        relax_input = dict(scf_input)
        relax_input["calculation"] = self.ctx.calculation
        for key in ("force_thr_ev", "relax_nmax"):
            if key in engine_options:
                relax_input[key] = engine_options[key]
        if "yascheduler" in self.ctx.codes["abacus"]:
            flat_output = Dict(dict={"flat_output": True})
        else:
            flat_output = None

        builder = AbacusRelaxWorkChain.get_builder()
        builder.structure = self.ctx.structure
        builder.base.abacus.code = load_code(self.ctx.codes["abacus"])
        builder.base.abacus.parameters = Dict(dict={"input": relax_input})
        if flat_output is not None:
            # Flat retrieve paths (see the patched aiida_abacus
            # make_retrieve_list): yascheduler downloads results flat,
            # and the spawn command copies OUT.*/* into the task dir.
            builder.base.abacus.settings = flat_output

        kpoints = KpointsData()
        kpoints.set_cell_from_structure(self.ctx.structure)
        kpoints.set_kpoints_mesh(list(engine_options.get("kpoints", [4, 4, 4])))
        builder.base.kpoints = kpoints

        if engine_options.get("pseudo_family"):
            builder.base.pseudo_family = Str(engine_options["pseudo_family"])

        abacus_metadata = {}
        if self.ctx.options_run:
            abacus_metadata["options"] = self.ctx.options_run
        builder.base.abacus.metadata = abacus_metadata

        builder.meta_convergence = Bool(False)
        builder.max_meta_convergence_iterations = Int(1)
        builder.metadata = {"label": f"{self.ctx.phase_label} - optimization"}

        future = self.submit(builder)
        return ToContext(optimization=future)

    def inspect_optimization(self):
        if not self.ctx.optimize or self.ctx.calculation == "scf":
            self.out("optimized_structure", self.ctx.optimized_structure)
            return

        opt_workchain = self.ctx.optimization
        if not opt_workchain.is_finished_ok:
            return self._child_exit_code(
                opt_workchain,
                "Optimization",
                self.exit_codes.ERROR_OPTIMIZATION_FAILED,
                forward_child_exit_code=False,
            )

        try:
            optimized_structure = opt_workchain.outputs.structure
        except Exception as exc:
            self.report(f"Could not extract optimized structure: {exc}")
            return self.exit_codes.ERROR_OPTIMIZATION_FAILED

        self.ctx.optimized_structure = optimized_structure
        self.out("optimized_structure", optimized_structure)

    def run_phonons(self):
        optimized_structure = self.ctx.optimized_structure

        phonon_params = self.ctx.config["calculations"]["phonons"]["parameters"]
        engine_options = self.ctx.config["options"]

        phonopy_parameters = {
            key.upper(): value
            for key, value in phonon_params.get(
                "phonopy_parameters", {"WRITE_FORCE_CONSTANTS": True}
            ).items()
        }

        scf_input = deepcopy(
            self.ctx.config.get("default", {}).get("scf", {}).get("input", {})
        )

        inputs = {
            "structure": optimized_structure,
            "supercell_matrix": List(list=phonon_params["supercell_matrix"]),
            "abacus_parameters": Dict(dict={"input": scf_input}),
            "code": Str(self.ctx.codes["abacus"]),
            "phonopy": {
                "code": load_code(self.ctx.codes["phonopy"]),
                "parameters": Dict(dict=phonopy_parameters),
            },
            "metadata": {"label": f"{self.ctx.phase_label} - phonons"},
        }
        for optional in ("pseudo_family", "kpoints_distance"):
            if optional in engine_options:
                inputs[optional] = (
                    Float(engine_options[optional])
                    if optional == "kpoints_distance"
                    else Str(engine_options[optional])
                )
        if self.ctx.options_run:
            inputs["options"] = Dict(dict=self.ctx.options_run)

        future = self.submit(PhonopyAbacusWorkChain, **inputs)
        return ToContext(phonons=future)

    def inspect_phonons(self):
        phonon_workchain = self.ctx.phonons
        if not phonon_workchain.is_finished_ok:
            return self._child_exit_code(
                phonon_workchain,
                "Phonon calculation",
                self.exit_codes.ERROR_PHONONS_FAILED,
                forward_child_exit_code=False,
            )

        # NB the base PhonopyWorkChain exposes a *namespace* output_phonopy
        # (output_force_constants, output_parameters, ...), which cannot be
        # re-attached as a single Dict output. The reporting tools read
        # force constants from the PhonopyAbacusWorkChain itself, so here we
        # only forward its Dict for provenance.
        if "output_phonopy" in phonon_workchain.outputs:
            phonopy_out = phonon_workchain.outputs.output_phonopy
            if hasattr(phonopy_out, "output_parameters"):
                self.out("output_phonopy", phonopy_out.output_parameters)

    def _child_exit_code(
        self,
        process,
        calculation_label,
        fallback,
        *,
        forward_child_exit_code=True,
    ):
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

        if forward_child_exit_code and exit_status is not None:
            return ExitCode(
                status=exit_status,
                message=exit_message or fallback.message,
            )

        return fallback
