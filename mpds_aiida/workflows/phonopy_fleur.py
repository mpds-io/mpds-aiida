from aiida.engine import WorkChain, ToContext
from aiida.orm import (
    ArrayData,
    Str,
    Dict,
    StructureData,
    RemoteData,
    load_code,
)
from aiida_fleur.workflows.scf import FleurScfWorkChain
from aiida_fleur.data.fleurinpmodifier import FleurinpModifier
from aiida_fleur.tools.common_fleur_wf import get_inputs_fleur
from aiida_fleur.workflows.base_fleur import FleurBaseWorkChain
from aiida.engine import ExitCode
from aiida_phonopy.workflows.phonopy import PhonopyWorkChain
import numpy as np

from aiida import load_profile

load_profile()


class FleurForcesWorkChain(WorkChain):
    """
    Runs FleurSCFWorkChain, then restarts Fleur with slightly changed input,
    copying all previous files except the input, which is modified ('l_f': True, 'f_level': 3).
    Parses the FORCES file from the final calculation as output.
    """

    @classmethod
    def define(cls, spec):
        super().define(spec)

        spec.exit_code(
            400,
            "ERROR_CANNOT_START_FORCE_CALCULATION",
            message="Could not start the force calculation. Please check input parameters and previous workflow steps.",
        )
        spec.exit_code(
            401,
            "ERROR_FORCES_FILE_PROCESSING_FAILED",
            message="Failed to process the FORCES file. The file may be corrupted or not retrieved properly.",
        )

        spec.input("fleur", valid_type=Str, required=True)
        spec.input("inpgen", valid_type=Str, required=False)
        spec.input("structure", valid_type=StructureData, required=True)
        spec.input("calc_parameters", valid_type=Dict, required=False)
        spec.input("wf_parameters", valid_type=Dict, required=False)
        spec.input("options", valid_type=Dict, required=False)
        spec.input(
            "settings",
            valid_type=Dict,
            required=False,
            default=lambda: Dict(
                dict={"additional_retrieve_list": ["FORCES"]}
            ),
        )
        spec.input("fleurinp", required=False)
        spec.input("remote_data", valid_type=RemoteData, required=False)
        spec.input("structure_label", valid_type=Str, required=False)
        spec.outline(
            cls.load_codes,
            cls.run_scf,
            cls.prepare_forces_input,
            cls.run_forces_calc,
            cls.parse_forces_file,
            cls.finalize,
        )
        spec.output("forces", valid_type=Dict, required=True)
        spec.expose_outputs(FleurScfWorkChain, namespace="scf")

    def load_codes(self):
        """
        Load the Fleur and inpgen codes from the inputs.
        """
        if isinstance(self.inputs.fleur, Str):
            self.inputs.fleur = load_code(self.inputs.fleur.value)
        if isinstance(self.inputs.fleur, str):
            self.inputs.fleur = load_code(self.inputs.fleur)
        if "inpgen" in self.inputs and isinstance(self.inputs.inpgen, Str):
            self.inputs.inpgen = load_code(self.inputs.inpgen.value)
        if "inpgen" in self.inputs and isinstance(self.inputs.inpgen, str):
            self.inputs.inpgen = load_code(self.inputs.inpgen)

    def run_scf(self):
        """
        Run FleurSCFWorkChain.
        """
        # to get rid of extra input parameters, we build new inputs dict
        inputs = {
            "fleur": self.inputs.fleur,
            "structure": self.inputs.structure,
        }
        if "inpgen" in self.inputs:
            inputs["inpgen"] = self.inputs.inpgen
        if "calc_parameters" in self.inputs:
            inputs["calc_parameters"] = self.inputs.calc_parameters
        if "wf_parameters" in self.inputs:
            inputs["wf_parameters"] = self.inputs.wf_parameters
        if "options" in self.inputs:
            inputs["options"] = self.inputs.options
        if "settings" in self.inputs:
            inputs["settings"] = self.inputs.settings
        if "fleurinp" in self.inputs:
            inputs["fleurinp"] = self.inputs.fleurinp
        if "remote_data" in self.inputs:
            inputs["remote_data"] = self.inputs.remote_data

        future = self.submit(FleurScfWorkChain, **inputs)
        return ToContext(scf_wc=future)

    def prepare_forces_input(self):
        """
        Modify the input from SCF calculation: set l_f=True, f_level=3.
        """
        # Get FleurinpData from SCF workchain output
        scf_wc = self.ctx.scf_wc
        fleurinp = (
            scf_wc.outputs.fleurinp if "fleurinp" in scf_wc.outputs else None
        )
        if fleurinp is None:
            fleurinp = scf_wc.outputs.last_calc.fleurinp  # fallback

        fleurmode = FleurinpModifier(fleurinp)
        fleurmode.set_inpchanges({"l_f": True, "f_level": 0})
        self.ctx.forces_fleurinp = fleurmode.freeze()
        # Also get the remote folder
        self.ctx.remote_folder = scf_wc.outputs.last_calc.remote_folder

    def run_forces_calc(self):
        """
        Run a Fleur calculation with modified input and previous remote files.
        """
        try:
            code = self.inputs.fleur
            remote = self.ctx.remote_folder
            fleurinp = self.ctx.forces_fleurinp
            options = (
                self.inputs.options.get_dict()
                if "options" in self.inputs
                else {}
            )
            label = "Fleur forces calculation"
            description = "Fleur run for forces after SCF"
            settings = (
                self.inputs.settings.get_dict()
                if "settings" in self.inputs
                else None
            )

            inputs_builder = get_inputs_fleur(
                code, remote, fleurinp, options, label, description, settings
            )
            future = self.submit(FleurBaseWorkChain, **inputs_builder)
            return ToContext(forces_calc=future)
        except Exception as e:
            self.report(f"Cannot start force calculation: {e}")
            return ExitCode(400, f"Cannot start force calculation: {e}")

    def parse_forces_file(self):
        """
        Read and parse the FORCES file from the retrieved folder of the forces calculation.
        Returns forces as a list of lists of floats in the output Dict.
        If file processing fails, exits with a special code.
        """
        forces_calc = self.ctx.forces_calc
        structure_number = (
            self.inputs.structure_label
            if "structure_label" in self.inputs
            else "1"
        )
        try:
            with forces_calc.outputs.retrieved.open("FORCES", "r") as handle:
                lines = handle.readlines()
            forces = []
            for line in lines:
                if "force" in line:
                    parts = line.split()
                    try:
                        vec = [
                            float(parts[0]),
                            float(parts[1]),
                            float(parts[2]),
                        ]
                        forces.append(vec)
                    except Exception:
                        continue
            forces_dict = {
                f"forces_{structure_number if isinstance(structure_number, (int, str)) else structure_number.value}": forces
            }
            self.ctx.forces_content = forces_dict
        except Exception as e:
            self.report(f"Error parsing FORCES file: {e}")
            # Exit with a special code if file processing fails
            return ExitCode(401, f"FORCES file processing failed: {e}")

    def finalize(self):
        """
        Output the parsed forces as Dict.
        """
        self.out(
            "forces",
            Dict(dict=self.ctx.forces_content).store(),
        )
        # Expose SCF outputs for convenience
        self.out_many(
            self.exposed_outputs(
                self.ctx.scf_wc, FleurScfWorkChain, namespace="scf"
            )
        )


class PhonopyFleurWorkChain(PhonopyWorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input(
            "fleur_parameters",
            valid_type=Dict,
            required=True,
            help="Fleur parameters for the Fleur calculation.",
        )

        spec.exit_code(
            402,
            "FORCES_DATA_NOT_FOUND",
            message="Failed to find forces data in the Fleur calculation outputs.",
        )

    def run_forces(self):
        """
        Run FleurForcesWorkChain for pristine and each displaced supercell.
        """
        # Get pristine supercell and all displaced supercells
        supercells_dict = self.ctx.preprocess_data.calcfunctions.get_supercells_with_displacements()
        futures = {}

        inputs = self.inputs.fleur_parameters.get_dict()

        # Run displaced supercells
        for label, structure in supercells_dict.items():
            number = label.split("_")[-1]
            self.report(f"submitting supercell: {number}")
            inputs["structure"] = structure
            inputs["structure_label"] = Str(number)
            futures[number] = self.submit(FleurForcesWorkChain, **inputs)

        self.report(f'Sending FleurForcesWorkChain for supercells: {list(futures.keys())}')
        # Store all futures in context for later inspection
        return ToContext(**{
            f"calc_forces_{number}": future for number, future in futures.items()
        })

    def inspect_forces(self):
        """
        Collect forces from each FleurForcesWorkChain and expose them as ArrayData in the output namespace.
        """

        supercells_dict = self.ctx.preprocess_data.calcfunctions.get_supercells_with_displacements()
        # all_labels = ["pristine"] + list(supercells_dict.keys())
        all_labels = list(i.split("_")[-1] for i in supercells_dict.keys())
        self.report(f"all_labels: {all_labels}")

        forces_dict = {}
        for label in all_labels:
            forces_wc = getattr(self.ctx, f"calc_forces_{label}", None)
            self.report(f"for {label} get forces_wc: {forces_wc}")
            if forces_wc is not None and "forces" in forces_wc.outputs:
                forces_out_dict = forces_wc.outputs["forces"].get_dict()
                self.report(f"forces_out_dict keys: {list(forces_out_dict.keys())}")
                key = f"forces_{label}"
                if key in forces_out_dict:
                    forces = forces_out_dict[key]
                    forces_array = np.array(forces, dtype=float)
                    # Convert Hrt/Bohr to eV/Angstrom
                    forces_array *= 51.4220823957
                    array = ArrayData()
                    array.set_array("forces", forces_array)
                    array.store()
                    forces_dict[key] = array
                else:
                    self.report(f"Key {key} not found in forces_out_dict for {label}")
                    return ExitCode(402, f"FORCES data not found for {label}")
            else:
                self.report(f"No forces data for {label}")
                return ExitCode(402, f"FORCES data not found for {label}")

        self.report(f"forces_dict: {forces_dict}")
        self.out("supercells_forces", forces_dict)


def test_forces_calulation():
    from aiida.engine import run
    from aiida.orm import StructureData, Dict
    from ase.spacegroup import crystal

    # Example usage
    fleur_name = "fleur@yascheduler"
    inpgen_name = "inpgen@local_machine"
    # Setup structure
    a = 5.511
    c = 7.796

    atoms = crystal(
        ["Sr", "Ti", "O", "O"],
        basis=[
            (0, 0, 0.25),
            (0.0, 0.5, 0.0),
            (0.2451, 0.7451, 0),
            (0, 0.5, 0.25),
        ],
        spacegroup=140,
        cellpar=[a, a, c, 90, 90, 90],
    )
    structure = StructureData(ase=atoms)
    # structure = load_node(215628)
    options = Dict(
        dict={
            "resources": {
                "num_machines": 1,
                "num_mpiprocs_per_machine": 1,
                "num_cores_per_mpiproc": 8,
            },
            "max_wallclock_seconds": 6 * 60 * 60,
        }
    )
    inputs = {
        "fleur": fleur_name,
        "inpgen": inpgen_name,
        "structure": structure,
        "options": options,
    }

    result = run(FleurForcesWorkChain, **inputs)
    print(result["forces"])


def test_phonopy_fleur():
    from aiida.engine import run_get_node
    from aiida.orm import StructureData
    from ase.spacegroup import crystal

    # Example usage
    fleur_name = "fleur@yascheduler"
    inpgen_name = "inpgen@local_machine"


    # Setup structure
    a = 5.511
    c = 7.796

    atoms = crystal(
        ["Sr", "Ti", "O", "O"],
        basis=[
            (0, 0, 0.25),
            (0.0, 0.5, 0.0),
            (0.2451, 0.7451, 0),
            (0, 0.5, 0.25),
        ],
        spacegroup=140,
        cellpar=[a, a, c, 90, 90, 90],
    )
    structure = StructureData(ase=atoms)

    options = {
        "resources": {
            "num_machines": 1,
            "num_mpiprocs_per_machine": 1,
            "num_cores_per_mpiproc": 8,
        },
        "max_wallclock_seconds": 6 * 60 * 60,
    }

    settings = {
        "fleur": fleur_name,
        "inpgen": inpgen_name,
        "options": options,
        "settings": {"additional_retrieve_list": ["FORCES"]},
    }

    inputs = {
        "structure": structure,
        "fleur_parameters": settings,
        "supercell_matrix": [[2, 0, 0], [0, 2, 0], [0, 0, 2]],
        "phonopy": {
            "code": load_code("phonopy@local_machine"),
            "parameters": Dict({"band": "auto"}),
        },
    }

    results, node = run_get_node(PhonopyFleurWorkChain, **inputs)
    ph = node.outputs.phonopy_data.get_phonopy_instance()
    ph.produce_force_constants()
    ph.auto_band_structure(plot=True).savefig("Al_band_structure.png")

if __name__ == "__main__":
     test_phonopy_fleur()
     # test_forces_calulation()