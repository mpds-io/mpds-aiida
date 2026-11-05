import numpy as np
from aiida.engine import ExitCode, ToContext, WorkChain
from aiida.orm import (
    ArrayData,
    Dict,
    Float,
    Str,
    StructureData,
    load_code,
)
from aiida_abacus.workflows.base import AbacusBaseWorkChain
from aiida_phonopy.workflows.phonopy import PhonopyWorkChain

from ..abacus_forces import read_scf_log, restore_force_order, scf_has_converged


class AbacusForcesWorkChain(WorkChain):
    """
    Single-point SCF calculation with forces on a (displaced) supercell.

    Wraps AbacusBaseWorkChain (restart logic, pseudo family resolution,
    automatic k-mesh) and exposes the parsed forces as a Dict output:
    {"forces_<structure_label>": [[Fx, Fy, Fz], ...]} in eV/Angstrom.
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input(
            "code",
            valid_type=Str,
            required=True,
            help="Label of the configured ABACUS code.",
        )
        spec.input("structure", valid_type=StructureData, required=True)
        spec.input(
            "parameters",
            valid_type=Dict,
            required=True,
            help="ABACUS INPUT parameters for the supercell SCF run. "
            "`calculation` is forced to `scf` and `cal_force` to 1.",
        )
        spec.input("pseudo_family", valid_type=Str, required=False)
        spec.input("kpoints_distance", valid_type=Float, required=False)
        spec.input(
            "options",
            valid_type=Dict,
            required=False,
            help="AiiDA metadata.options for the ABACUS CalcJob.",
        )
        spec.input(
            "structure_label",
            valid_type=Str,
            required=False,
            default=lambda: Str("1"),
            help="Suffix of the supercell, used as the forces key.",
        )

        spec.exit_code(
            400,
            "ERROR_SCF_FAILED",
            message="The ABACUS SCF workchain did not finish successfully.",
        )
        spec.exit_code(
            401,
            "ERROR_NO_FORCES",
            message="No forces were found in the parsed output.",
        )
        spec.exit_code(
            402,
            "ERROR_WRONG_FORCES_UNIT",
            message="Forces are not in eV/Angstrom, refusing to pass them to phonopy.",
        )

        spec.exit_code(
            404,
            "ERROR_FORCE_ORDER",
            message="Forces cannot be matched to the input atoms.",
        )
        spec.exit_code(
            405,
            "ERROR_SCF_NOT_CONVERGED",
            message="The final ABACUS SCF log does not establish convergence.",
        )

        spec.outline(
            cls.run_scf,
            cls.inspect_scf,
            cls.finalize,
        )

        spec.output(
            "forces",
            valid_type=Dict,
            help="Forces on all atoms of the supercell, eV/Angstrom.",
        )
        spec.output("misc", valid_type=Dict, required=False)
        spec.output("force_order", valid_type=Dict, required=False)

    def run_scf(self):
        builder = AbacusBaseWorkChain.get_builder()
        builder.abacus.code = load_code(self.inputs.code.value)
        builder.abacus.structure = self.inputs.structure

        parameters = self.inputs.parameters.get_dict()
        parameters.setdefault("input", {})
        parameters["input"]["calculation"] = "scf"
        parameters["input"]["cal_force"] = 1
        builder.abacus.parameters = Dict(dict=parameters)

        if "yascheduler" in self.inputs.code.value:
            # Flat retrieve paths (see the patched aiida_abacus
            # make_retrieve_list): yascheduler downloads results flat,
            # and the spawn command copies OUT.*/* into the task dir.
            builder.abacus.settings = Dict(dict={"flat_output": True})

        if "pseudo_family" in self.inputs:
            builder.pseudo_family = self.inputs.pseudo_family
        if "kpoints_distance" in self.inputs:
            builder.kpoints_distance = self.inputs.kpoints_distance

        metadata = {"call_link_label": "scf"}
        if "options" in self.inputs:
            metadata["options"] = self.inputs.options.get_dict()
        builder.abacus.metadata = metadata

        future = self.submit(AbacusBaseWorkChain, **dict(builder))
        self.report(f"Submitting AbacusBaseWorkChain<{future.pk}> for forces")
        return ToContext(scf=future)

    def inspect_scf(self):
        scf = self.ctx.scf
        if not scf.is_finished_ok:
            self.report(
                f"ABACUS SCF workchain failed with exit status {scf.exit_status}"
            )
            return self.exit_codes.ERROR_SCF_FAILED
        try:
            calculation = scf.outputs.misc.creator
            log = read_scf_log(calculation)
        except (AttributeError, KeyError, OSError, ValueError) as exc:
            self.report(f"Cannot verify SCF convergence: {exc}")
            return self.exit_codes.ERROR_SCF_NOT_CONVERGED
        if not scf_has_converged(log):
            self.report("Refusing forces without convergence in the final SCF log")
            return self.exit_codes.ERROR_SCF_NOT_CONVERGED

    def finalize(self):
        misc = self.ctx.scf.outputs.misc.get_dict()
        forces = misc.get("final_forces")
        if not forces:
            self.report("No forces parsed from the ABACUS output")
            return self.exit_codes.ERROR_NO_FORCES

        unit = str(misc.get("force_unit", ""))
        if unit.lower().replace(" ", "") not in ("ev/angstrom", "ev/ang", "ev/å"):
            self.report(f"Unexpected forces unit '{unit}', expected eV/Angstrom")
            return self.exit_codes.ERROR_WRONG_FORCES_UNIT

        try:
            calculation = self.ctx.scf.outputs.misc.creator
            if (
                calculation is None
                or calculation.inputs.parameters.get_dict()["input"]["calculation"]
                != "scf"
            ):
                raise ValueError(
                    "Force output must come from a single-point SCF CalcJob"
                )
            stru = calculation.base.repository.get_object_content("STRU")
            forces, permutation = restore_force_order(
                self.inputs.structure, forces, stru
            )
        except (ValueError, KeyError, OSError, IndexError) as exc:
            self.report(f"Cannot restore force order: {exc}")
            return self.exit_codes.ERROR_FORCE_ORDER

        label = self.inputs.structure_label.value
        self.out(
            "forces",
            Dict(dict={f"forces_{label}": forces}).store(),
        )
        self.out("misc", self.ctx.scf.outputs.misc)
        self.out(
            "force_order",
            Dict(
                dict={
                    "abacus_to_structure": permutation,
                    "source_calcjob_uuid": str(calculation.uuid),
                }
            ).store(),
        )


class PhonopyAbacusWorkChain(PhonopyWorkChain):
    """
    Frozen phonons with ABACUS: phonopy generates the supercells with
    displacements, ABACUS computes forces, phonopy builds the force
    constants and thermal properties.
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input(
            "abacus_parameters",
            valid_type=Dict,
            required=True,
            help="ABACUS INPUT parameters for the supercell SCF runs. "
            "`calculation` is forced to `scf` and `cal_force` to 1.",
        )
        spec.input(
            "code", valid_type=Str, required=True, help="Label of the ABACUS code."
        )
        spec.input("pseudo_family", valid_type=Str, required=False)
        spec.input("kpoints_distance", valid_type=Float, required=False)
        spec.input(
            "options",
            valid_type=Dict,
            required=False,
            help="AiiDA metadata.options for every ABACUS CalcJob.",
        )
        spec.exit_code(
            402,
            "FORCES_DATA_NOT_FOUND",
            message="Failed to find forces data in the ABACUS calculation outputs.",
        )

    def run_forces(self):
        """Run AbacusForcesWorkChain for each displaced supercell."""
        supercells_dict = (
            self.ctx.preprocess_data.calcfunctions.get_supercells_with_displacements()
        )
        futures = {}

        # The displacement number stays bracket-free on purpose: the MPDS
        # monitor's archive naming strips a trailing "[n]" from labels, so
        # every displacement would collide on one directory name.
        for label, structure in supercells_dict.items():
            number = label.split("_")[-1]
            self.report(f"Submitting ABACUS forces calculation for supercell {number}")

            inputs = {
                "code": self.inputs.code,
                "structure": structure,
                "parameters": self.inputs.abacus_parameters,
                "structure_label": Str(number),
                "metadata": {
                    "label": f"{self.node.label or 'Abacus phonons'} [{number}]"
                },
            }
            for optional in ("pseudo_family", "kpoints_distance", "options"):
                if optional in self.inputs:
                    inputs[optional] = self.inputs[optional]

            futures[number] = self.submit(AbacusForcesWorkChain, **inputs)

        self.report(
            f"Sending AbacusForcesWorkChain for supercells: {list(futures.keys())}"
        )
        return ToContext(
            **{f"calc_forces_{number}": future for number, future in futures.items()}
        )

    def inspect_forces(self):
        """Collect forces from each AbacusForcesWorkChain and expose them as ArrayData."""
        supercells_dict = (
            self.ctx.preprocess_data.calcfunctions.get_supercells_with_displacements()
        )
        all_labels = [label.split("_")[-1] for label in supercells_dict.keys()]

        forces_dict = {}
        for label in all_labels:
            forces_wc = getattr(self.ctx, f"calc_forces_{label}", None)
            if forces_wc is None or not forces_wc.is_finished_ok:
                self.report(f"ABACUS forces calculation for supercell {label} failed")
                return ExitCode(402, f"FORCES data not found for {label}")

            forces_out_dict = forces_wc.outputs["forces"].get_dict()
            key = f"forces_{label}"
            if key not in forces_out_dict:
                self.report(f"Key {key} not found in forces output for {label}")
                return ExitCode(402, f"FORCES data not found for {label}")

            forces_array = np.array(forces_out_dict[key], dtype=float)
            array = ArrayData()
            array.set_array("forces", forces_array)
            array.store()
            forces_dict[key] = array

        self.out("supercells_forces", forces_dict)
