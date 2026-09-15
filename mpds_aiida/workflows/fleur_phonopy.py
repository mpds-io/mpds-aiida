import numpy as np
from lxml import etree
from aiida.engine import ExitCode, ToContext, WorkChain
from aiida.orm import (
    ArrayData,
    Bool,
    Dict,
    Int,
    KpointsData,
    RemoteData,
    Str,
    StructureData,
    load_code,
)
from aiida_fleur.data.fleurinpmodifier import FleurinpModifier
from aiida_fleur.tools.common_fleur_wf import get_inputs_fleur
from aiida_fleur.workflows.base_fleur import FleurBaseWorkChain
from aiida_fleur.workflows.scf import FleurScfWorkChain
from aiida_phonopy.workflows.phonopy import PhonopyWorkChain
from aiida_reoptimize.structure.fleur_utils import (
    Fleur_setup,
    convert_xml_to_FleurInpData,
)
from aiida_reoptimize.structure.magmoms_utils import (
    reverse_structure_data,
)
from ase.units import Bohr, Hartree

HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM = Hartree / Bohr  # 27.211386245988 / 0.529177210903


def _get_kpoint_mesh_dims(xml_content: str) -> tuple[int, int, int]:
    """Read nx/ny/nz off the active (type="mesh") kPointList in an inp.xml
    string. These are metadata only -- see retry_scf_with_denser_kmesh for
    why they can't just be edited in place to change the actual mesh.

    Raises ValueError if the kPointList tag or its nx/ny/nz attributes are
    not found: a silent fallback to (1, 1, 1) would produce a Gamma-only
    mesh without any warning, which has no physical justification.
    """
    root = etree.fromstring(xml_content.encode("utf-8"))
    for e in root.iter():
        if not isinstance(e.tag, str):
            continue
        if e.tag.split("}")[-1] == "kPointList" and e.get("type") == "mesh":
            nx = e.get("nx")
            ny = e.get("ny")
            nz = e.get("nz")
            if nx is None or ny is None or nz is None:
                raise ValueError(
                    "kPointList type='mesh' found but missing nx/ny/nz attributes"
                )
            return int(float(nx)), int(float(ny)), int(float(nz))
    raise ValueError("kPointList type='mesh' not found in inp.xml")


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
        spec.exit_code(
            402,
            "ERROR_PARENT_SCF_FAILED",
            message="The parent SCF calculation did not finish successfully; no charge "
            "density available to continue from into the forces step.",
        )

        spec.input("fleur", valid_type=Str, required=True)
        spec.input("inpgen", valid_type=Str, required=False)
        spec.input("structure", valid_type=StructureData, required=False)
        spec.input("calc_parameters", valid_type=Dict, required=False)
        spec.input("wf_parameters", valid_type=Dict, required=False)
        spec.input("options", valid_type=Dict, required=False)
        spec.input(
            "settings",
            valid_type=Dict,
            required=False,
            default=lambda: Dict(dict={"additional_retrieve_list": ["FORCES"]}),
        )
        spec.input("fleurinp", required=False)
        spec.input("remote_data", valid_type=RemoteData, required=False)
        spec.input("structure_label", valid_type=Str, required=False)
        spec.input("f_level", valid_type=Int, required=False, default=lambda: Int(0))
        spec.outline(
            cls.load_codes,
            cls.run_scf,
            cls.retry_scf_with_denser_kmesh,
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
        # Build inputs dict, only including present keys
        inputs = {"fleur": self.inputs.fleur}
        for key in (
            "inpgen",
            "calc_parameters",
            "wf_parameters",
            "options",
            "settings",
            "fleurinp",
            "remote_data",
        ):
            if key in self.inputs:
                inputs[key] = self.inputs[key]
        if "structure" in self.inputs and "fleurinp" not in self.inputs:
            inputs["structure"] = self.inputs.structure

        future = self.submit(FleurScfWorkChain, **inputs)
        return ToContext(scf_wc=future)

    def retry_scf_with_denser_kmesh(self):
        """
        If the SCF did not converge, retry it once with a denser k-point
        mesh (nx/ny/nz multiplied by 1.5, rounded up), continuing from the
        existing charge density. Only one retry is attempted. If it still
        doesn't converge, self.ctx.scf_wc is left as the retry's result and
        prepare_forces_input's is_finished_ok check reports the failure.

        Increasing the k-point sampling is the standard approach for
        improving SCF convergence (as done in CRYSTAL). The factor 1.5 is
        a compromise between accuracy and cost: e.g. 2x6x4 -> 3x9x6.

        An earlier version of this method only edited the nx/ny/nz
        *attributes* on the kPointList element. That is a no-op: inp.xml's
        type="mesh" kPointList stores the actual, already symmetry-reduced
        k-points as explicit <kPoint> children, and nothing regenerates
        that list from nx/ny/nz -- neither FLEUR nor aiida-fleur reads the
        attributes back to rebuild the list. This version instead builds a
        real KpointsData for the denser mesh (unreduced Monkhorst-Pack
        grid; no symmetry reduction, but a strictly denser set of points)
        and writes it in via FleurinpModifier.set_kpointsdata, which
        regenerates the actual <kPoint> list and switches inp.xml to use it.
        """
        import math

        if self.ctx.scf_wc.is_finished_ok:
            return
        if self.ctx.get("scf_kmesh_retried"):
            return
        self.ctx.scf_kmesh_retried = True

        failed_wc = self.ctx.scf_wc
        self.report(
            f"SCF workchain <{failed_wc.pk}> did not converge "
            f"(exit_status={failed_wc.exit_status}); retrying once with a "
            f"denser k-point mesh (x1.5), continuing from the existing "
            f"charge density."
        )

        old_fleurinp = failed_wc.outputs.fleurinp
        remote_folder = failed_wc.outputs.last_calc.remote_folder

        cur_nx, cur_ny, cur_nz = _get_kpoint_mesh_dims(
            old_fleurinp.get_content("inp.xml")
        )
        nx, ny, nz = (math.ceil(d * 1.5) for d in (cur_nx, cur_ny, cur_nz))
        self.report(
            f"k-point mesh {[cur_nx, cur_ny, cur_nz]} -> {[nx, ny, nz]} "
            f"({nx * ny * nz} unreduced points)"
        )

        raw_points = [
            [i / nx, j / ny, k / nz]
            for i in range(nx)
            for j in range(ny)
            for k in range(nz)
        ]
        weights = [1.0 / len(raw_points)] * len(raw_points)

        kpoints = KpointsData()
        kpoints.set_cell_from_structure(old_fleurinp.get_structuredata())
        kpoints.set_kpoints(raw_points, cartesian=False, weights=weights)
        kpoints.store()

        mod = FleurinpModifier(old_fleurinp)
        mod.set_kpointsdata(
            kpoints, name="denser_retry", switch=True, kpoint_type="mesh"
        )
        new_fleurinp = mod.freeze()

        # Give the retry one long continuous run: itmax_per_run tripled,
        # fleur_runmax forced to 1. FleurScfWorkChain's internal
        # restart-across-runs does not reliably carry the evolving charge
        # density forward, so more restarts are ineffective. Only
        # iterations within a single continuous FLEUR run reliably
        # progress the charge distance.
        inputs = {
            "fleur": self.inputs.fleur,
            "fleurinp": new_fleurinp,
            "remote_data": remote_folder,
        }
        for key in ("options", "settings"):
            if key in self.inputs:
                inputs[key] = self.inputs[key]
        retry_wf_parameters = (
            dict(self.inputs.wf_parameters.get_dict())
            if "wf_parameters" in self.inputs
            else {}
        )
        retry_wf_parameters["itmax_per_run"] = int(
            retry_wf_parameters.get("itmax_per_run", 300) * 1.5
        )
        retry_wf_parameters["fleur_runmax"] = 1
        inputs["wf_parameters"] = Dict(dict=retry_wf_parameters)

        future = self.submit(FleurScfWorkChain, **inputs)
        return ToContext(scf_wc=future)

    def prepare_forces_input(self):
        """
        Modify the input from SCF calculation: set l_f=True, f_level from inputs.
        """
        # Get FleurinpData from SCF workchain output
        scf_wc = self.ctx.scf_wc
        if not scf_wc.is_finished_ok:
            self.report(
                f"Parent SCF workchain <{scf_wc.pk}> did not finish successfully "
                f"(exit_status={scf_wc.exit_status}); cannot continue to forces step."
            )
            return self.exit_codes.ERROR_PARENT_SCF_FAILED
        fleurinp = scf_wc.outputs.fleurinp if "fleurinp" in scf_wc.outputs else None
        if fleurinp is None:
            fleurinp = scf_wc.outputs.last_calc.fleurinp  # fallback

        fleurmode = FleurinpModifier(fleurinp)
        # Get f_level from inputs, default to 0 if not provided
        f_level = self.inputs.get("f_level", Int(0))
        fleurmode.set_inpchanges({"l_f": True, "f_level": f_level.value})
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
                else {
                    "custom_scheduler_commands": "",
                    "environment_variables": {},
                    "import_sys_environment": False,
                    "max_wallclock_seconds": 4 * 10**5,
                    "optimize_resources": True,
                    "queue_name": "",
                    "resources": {
                        "num_machines": 1,
                        "num_mpiprocs_per_machine": 1,
                    },
                    "withmpi": True,
                }
            )
            label = "Fleur forces calculation"
            description = "Fleur run for forces after SCF"
            settings = (
                self.inputs.settings.get_dict() if "settings" in self.inputs else None
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
        Read and parse forces from the retrieved folder of the forces calculation.

        Tries the standalone FORCES file first (written by some FLEUR versions).
        If FORCES is not present, falls back to parsing forces from out.xml
        (totalForcesOnRepresentativeAtoms/forceTotal tags), expanding
        representative-atom forces to all atoms using inp.xml atomGroup counts.

        Returns forces as a list of [Fx, Fy, Fz] in Hartree/Bohr
        (inspect_forces converts to eV/Angstrom downstream).
        If processing fails, exits with code 401.
        """
        forces_calc = self.ctx.forces_calc
        structure_number = (
            self.inputs.structure_label if "structure_label" in self.inputs else "1"
        )
        try:
            retrieved = forces_calc.outputs.retrieved
            retrieved_files = retrieved.list_object_names()

            forces = []

            if "FORCES" in retrieved_files:
                # --- Path 1: standalone FORCES file (original behaviour) ---
                with retrieved.open("FORCES", "r") as handle:
                    lines = handle.readlines()
                for line in lines:
                    parts = line.split()
                    if len(parts) == 4 and parts[-1] == "force":
                        try:
                            forces.append(
                                [float(parts[0]), float(parts[1]), float(parts[2])]
                            )
                        except ValueError:
                            self.report(f"Could not parse force line: {line}")
                            raise
            elif "out.xml" in retrieved_files:
                # --- Path 2: extract forces from out.xml (FLEUR 6.2) ---
                from lxml import etree as _etree

                xml_content = retrieved.get_object_content("out.xml")
                if not xml_content:
                    return ExitCode(401, "out.xml is empty or unreadable")

                parser = _etree.XMLParser(recover=True, huge_tree=True)
                root = _etree.fromstring(
                    xml_content.encode("utf-8")
                    if isinstance(xml_content, str)
                    else xml_content,
                    parser,
                )
                if root is None:
                    return ExitCode(401, "Could not parse out.xml")

                raw_forces = []
                # Find all iterations and take forceTotal only from the LAST one
                iterations = [
                    e
                    for e in root.iter()
                    if isinstance(e.tag, str) and e.tag.split("}")[-1] == "iteration"
                ]
                if iterations:
                    # Use only the last iteration's forceTotal
                    last_iter = iterations[-1]
                    for e in last_iter.iter():
                        if not isinstance(e.tag, str):
                            continue
                        if e.tag.split("}")[-1] == "forceTotal":
                            fx, fy, fz = e.get("F_x"), e.get("F_y"), e.get("F_z")
                            if fx is not None and fy is not None and fz is not None:
                                raw_forces.append([float(fx), float(fy), float(fz)])
                else:
                    # Fallback: no iteration tags, take all forceTotal
                    for e in root.iter():
                        if not isinstance(e.tag, str):
                            continue
                        if e.tag.split("}")[-1] == "forceTotal":
                            fx, fy, fz = e.get("F_x"), e.get("F_y"), e.get("F_z")
                            if fx is not None and fy is not None and fz is not None:
                                raw_forces.append([float(fx), float(fy), float(fz)])

                if not raw_forces:
                    return ExitCode(
                        401,
                        "No forceTotal entries found in out.xml",
                    )

                # Expand representative-atom forces to all atoms using inp.xml
                if "inp.xml" in retrieved_files:
                    inp_content = retrieved.get_object_content("inp.xml")
                    inp_root = _etree.fromstring(
                        inp_content.encode("utf-8")
                        if isinstance(inp_content, str)
                        else inp_content,
                        _etree.XMLParser(recover=True, huge_tree=True),
                    )
                    group_counts = []
                    if inp_root is not None:
                        for ag in inp_root.iter():
                            if not isinstance(ag.tag, str):
                                continue
                            if ag.tag.split("}")[-1] == "atomGroup":
                                n = sum(
                                    1
                                    for child in ag
                                    if isinstance(child.tag, str)
                                    and child.tag.split("}")[-1] in ("relPos", "absPos")
                                )
                                group_counts.append(max(1, n))

                    if group_counts:
                        forces = []
                        for i, f in enumerate(raw_forces):
                            n = group_counts[i] if i < len(group_counts) else 1
                            for _ in range(n):
                                forces.append(list(f))
                        self.report(
                            f"Expanded {len(raw_forces)} representative "
                            f"forces to {len(forces)} atom forces "
                            f"(group_counts={group_counts})"
                        )
                    else:
                        forces = raw_forces
                        self.report(
                            "No atomGroup info in inp.xml, "
                            "using forces as-is (no expansion)"
                        )
                else:
                    forces = raw_forces
                    self.report(
                        "inp.xml not in retrieved, using forces as-is (no expansion)"
                    )
            else:
                return ExitCode(
                    401,
                    "Neither FORCES nor out.xml found in retrieved files: "
                    f"{retrieved_files}",
                )

            if not forces:
                return ExitCode(401, "No forces parsed from FORCES or out.xml")

            forces_dict = {
                f"forces_{structure_number if isinstance(structure_number, (int, str)) else structure_number.value}": forces
            }
            self.ctx.forces_content = forces_dict

        except Exception as e:
            self.report(f"Error parsing forces: {e}")
            return ExitCode(401, f"Forces processing failed: {e}")

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
            self.exposed_outputs(self.ctx.scf_wc, FleurScfWorkChain, namespace="scf")
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

        spec.input(
            "magmoms_mapper",
            valid_type=Dict,
            required=False,
            help="magmoms mapper dict for setting initial magnetic moments in the supercells.",
        )

        spec.input(
            "test_magmoms_run",
            valid_type=Bool,
            required=False,
            default=lambda: Bool(False),
            help="If True, prints info from fleur inp.xml and stops without running calculations.",
        )

        spec.exit_code(
            402,
            "FORCES_DATA_NOT_FOUND",
            message="Failed to find forces data in the Fleur calculation outputs.",
        )

        spec.exit_code(
            403,
            "ERROR_XML_VALIDATION_FAILED",
            message="Failed to validate the generated inp.xml file.",
        )

        spec.exit_code(
            404,
            "TEST_MAGMOMS_RUN",
            message="TEST_MAGMOMS_RUN is set to True, so the workflow stopped after printing inp.xml info.",
        )

    def run_forces(self):
        """
        Run FleurForcesWorkChain for pristine and each displaced supercell.
        """
        # Get pristine supercell and all displaced supercells
        supercells_dict = (
            self.ctx.preprocess_data.calcfunctions.get_supercells_with_displacements()
        )
        futures = {}
        magmoms_mapper = (
            self.inputs["magmoms_mapper"].get_dict()
            if self.inputs.get("magmoms_mapper", None)
            else None
        )

        inputs = self.inputs.fleur_parameters.get_dict()
        xml_input = None

        # Run displaced supercells
        for label, structure in supercells_dict.items():
            number = label.split("_")[-1]
            self.report(f"submitting supercell: {number}")
            # It creates ASE.atoms and generates inp.xml
            if "magmoms_mapper" in self.inputs:
                atoms = reverse_structure_data(structure, magmoms_mapper)
            else:
                atoms = structure.get_ase()

            fleur_setup = Fleur_setup(atoms)
            error = fleur_setup.validate()
            if error:
                self.report(f"Validation error: {error}")
                return ExitCode(403, f"Validation error: {error}")
            else:
                xml_input = fleur_setup.get_input_setup(label="Fe_fcc")
                fleur_inp_data = convert_xml_to_FleurInpData(xml_input)
                inputs["fleurinp"] = fleur_inp_data

            if self.inputs.get("test_magmoms_run", Bool(False)).value:
                if xml_input:
                    last_lines = xml_input.split("\n")[-50:]
                    self.report("Last 50 lines of inp.xml:")
                    self.report("\n".join(last_lines))
                return ExitCode(404)

            inputs["structure_label"] = Str(number)
            futures[number] = self.submit(FleurForcesWorkChain, **inputs)

        self.report(
            f"Sending FleurForcesWorkChain for supercells: {list(futures.keys())}"
        )
        # Store all futures in context for later inspection
        return ToContext(
            **{f"calc_forces_{number}": future for number, future in futures.items()}
        )

    def inspect_forces(self):
        """
        Collect forces from each FleurForcesWorkChain and expose them as ArrayData in the output namespace.
        """

        supercells_dict = (
            self.ctx.preprocess_data.calcfunctions.get_supercells_with_displacements()
        )
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
                    forces_array *= HARTREE_PER_BOHR_TO_EV_PER_ANGSTROM
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
