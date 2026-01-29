import copy
import re

import numpy as np
from aiida.common import NotExistent
from aiida.engine import ToContext, WorkChain, if_
from aiida.orm import (
    Code,
    Dict,
    RemoteData,
    Str,
    StructureData,
    XyData,
    load_code,
    load_node,
)
from aiida_fleur.data.fleurinp import (
    FleurinpData,
    get_fleurinp_from_remote_data,
)
from aiida_fleur.data.fleurinpmodifier import FleurinpModifier
from aiida_fleur.tools.common_fleur_wf import (
    get_inputs_fleur,
    test_and_get_codenode,
)
from aiida_fleur.workflows.base_fleur import FleurBaseWorkChain
from aiida_fleur.workflows.scf import FleurScfWorkChain
from scipy import constants as const
from scipy.integrate import simpson
from scipy.optimize import root_scalar
from scipy.special import expit

AngsCubeToCmCube = 1e-24  # 1 A**3 = 1e-24 cm**3


class FleurDOSLocalWorkChain(WorkChain):
    """
    WorkChain that:
    1. (Optional) Performs SCF convergence to obtain charge density
    2. Calculates DOS with 48x48x48 k-mesh
    3. Computes Seebeck coefficient from parsed DOS

    Supports three input configurations:
    • scf namespace → run SCF first, then DOS
    • remote only → use existing charge density for DOS
    • remote + fleurinp → use remote's charge density, fleurinp's structure/parameters
    """

    _default_wf_para = {
        "kpoints_mesh_dos": [48, 48, 48],  # ONLY for DOS calculation
        "sigma": 0.002,
        "emin": -2.0,  # Hrt
        "emax": 2.0,  # Hrt
        "numberPoints": 2000,
        "mode": "dos",
        "kpath": "skip",
        "add_comp_para": {
            "only_even_MPI": False,
            "max_queue_nodes": 20,
            "max_queue_wallclock_sec": 86400,
        },
        "inpxml_changes": [],
    }

    _default_options = {
        "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 4},
        "max_wallclock_seconds": 3600 * 10**3,
        "withmpi": True,
        "queue_name": "",
        "custom_scheduler_commands": "",
        "import_sys_environment": False,
        "environment_variables": {},
    }

    @classmethod
    def define(cls, spec):
        super().define(spec)

        # Expose SCF inputs in 'scf' namespace (optional)
        spec.expose_inputs(
            FleurScfWorkChain,
            namespace="scf",
            namespace_options={"required": False, "populate_defaults": False},
        )

        # Required inputs
        spec.input("fleur", valid_type=Code, required=True)

        # Optional inputs (mutually exclusive configurations)
        spec.input("remote", valid_type=RemoteData, required=False)
        spec.input("fleurinp", valid_type=FleurinpData, required=False)
        spec.input("structure", valid_type=StructureData, required=False)
        spec.input("wf_parameters", valid_type=Dict, required=False)
        spec.input("options", valid_type=Dict, required=False)
        spec.input("seebeck_parameters", valid_type=Dict, required=False)
        spec.input("label", valid_type=Str, required=False)

        # Context variables
        spec.outline(
            cls.validate_inputs,
            if_(cls.scf_needed)(
                cls.run_scf,
                cls.prepare_dos_from_scf,
            ).else_(
                cls.prepare_dos_from_remote,
            ),
            cls.run_dos_calculation,
            cls.parse_local_files,
            cls.calculate_seebeck_coefficient,
            cls.return_results,
        )

        # Outputs
        spec.output("output_dos_local_wc_para", valid_type=Dict)
        spec.output("output_dos_xy", valid_type=XyData, required=False)
        spec.output("output_seebeck", valid_type=Dict, required=False)
        spec.expose_outputs(FleurBaseWorkChain, namespace="dos_calc")

        # Exit codes
        spec.exit_code(
            230,
            "ERROR_INVALID_INPUT_PARAM",
            message="Invalid workchain parameters",
        )
        spec.exit_code(
            231,
            "ERROR_INVALID_INPUT_CONFIG",
            message="Invalid input configuration (scf+remote/fleurinp forbidden)",
        )
        spec.exit_code(
            233,
            "ERROR_INVALID_CODE_PROVIDED",
            message="Invalid FLEUR code node",
        )
        spec.exit_code(
            235,
            "ERROR_CHANGING_FLEURINPUT_FAILED",
            message="Input file modification failed",
        )
        spec.exit_code(
            236,
            "ERROR_INVALID_INPUT_FILE",
            message="Input file corrupted after modifications",
        )
        spec.exit_code(
            334,
            "ERROR_SCF_CALCULATION_FAILED",
            message="SCF calculation failed",
        )
        spec.exit_code(
            335,
            "ERROR_SCF_NO_REMOTE",
            message="No remote folder found after SCF",
        )
        spec.exit_code(
            401,
            "ERROR_NO_LOCAL_FILES",
            message="Local.1 file not found",
        )
        spec.exit_code(
            402,
            "ERROR_DOS_PARSING_FAILED",
            message="Failed to parse DOS from Local files",
        )
        spec.exit_code(
            403,
            "ERROR_SEEBECK_CALCULATION_FAILED",
            message="Seebeck coefficient calculation failed",
        )

    def validate_inputs(self):
        """Validate input configuration and initialize context"""
        self.report("Started FleurDOSLocalWorkChain")

        # Validate FLEUR code
        try:
            test_and_get_codenode(self.inputs.fleur, "fleur.fleur")
        except ValueError as exc:
            self.report(f"Invalid FLEUR code: {exc}")
            return self.exit_codes.ERROR_INVALID_CODE_PROVIDED

        # Determine workflow mode
        has_scf = "scf" in self.inputs
        has_remote = "remote" in self.inputs
        has_fleurinp = "fleurinp" in self.inputs

        # Enforce mutually exclusive configurations
        if has_scf and (has_remote or has_fleurinp):
            self.report(
                "ERROR: SCF namespace cannot be combined with remote or fleurinp"
            )
            return self.exit_codes.ERROR_INVALID_INPUT_CONFIG

        if not (has_scf or has_remote):
            self.report('ERROR: Need either "scf" namespace OR "remote" input')
            return self.exit_codes.ERROR_INVALID_INPUT_CONFIG

        self.ctx.scf_needed = has_scf
        self.ctx.successful = False

        # Initialize workflow parameters
        wf_default = copy.deepcopy(self._default_wf_para)
        if "wf_parameters" in self.inputs:
            wf_dict = self.inputs.wf_parameters.get_dict()
            # Validate extra keys
            extra_keys = [k for k in wf_dict if k not in wf_default]
            if extra_keys:
                self.report(
                    f"WARNING: wf_parameters contains extra keys: {extra_keys}"
                )
        else:
            wf_dict = wf_default

        # Merge defaults with user input
        for key, val in wf_default.items():
            wf_dict.setdefault(key, val)
        self.ctx.wf_dict = wf_dict

        # Initialize options
        opt_default = copy.deepcopy(self._default_options)
        if "options" in self.inputs:
            opt_dict = self.inputs.options.get_dict()
            for key, val in opt_default.items():
                opt_dict.setdefault(key, val)
        else:
            opt_dict = opt_default
        self.ctx.options = opt_dict

        # Initialize Seebeck parameters
        default_seebeck = {
            "temperature": 5.0,
            "carrier_type": "hole",
            "doping_cm3": 5e18,
            "fermi_energy_ev": 0.0,
        }
        if "seebeck_parameters" in self.inputs:
            user_params = self.inputs.seebeck_parameters.get_dict()
            default_seebeck.update(user_params)
        self.ctx.seebeck_params = default_seebeck

        if "label" in self.inputs:
            self.ctx.label = self.inputs.label.value
        else:
            self.ctx.label = "Fleur"

        self.report(
            f'Workflow mode: {"SCF + DOS" if self.ctx.scf_needed else "DOS only"}'
        )
        self.report(f'DOS k-mesh: {wf_dict["kpoints_mesh_dos"]}')
        return

    def scf_needed(self) -> bool:
        """Condition for outline: whether SCF convergence is required"""
        return self.ctx.scf_needed

    def run_scf(self):
        """Submit SCF workchain to converge charge density"""
        self.report("Launching SCF workchain to converge charge density...")

        # Get SCF inputs from exposed namespace
        scf_inputs = self.inputs.scf

        # Ensure structure or fleurinp is provided in SCF namespace
        if "structure" not in scf_inputs and "fleurinp" not in scf_inputs:
            self.report(
                'ERROR: SCF namespace must contain "structure" or "fleurinp"'
            )
            return self.exit_codes.ERROR_INVALID_INPUT_CONFIG

        # Submit SCF workchain
        future = self.submit(FleurScfWorkChain, **scf_inputs)
        self.report(f"Submitted SCF workchain: PK={future.pk}")
        return ToContext(scf_wc=future)

    def prepare_dos_from_scf(self):
        """Prepare DOS calculation after successful SCF convergence"""
        # Check SCF success
        if not self.ctx.scf_wc.is_finished_ok:
            self.report(f"SCF workchain failed (PK={self.ctx.scf_wc.pk})")
            return self.exit_codes.ERROR_SCF_CALCULATION_FAILED

        # Get remote folder from last FleurBaseWorkChain in SCF
        try:
            remote_folder = self._get_remote_from_scf(self.ctx.scf_wc)
        except RuntimeError as exc:
            self.report(f"Failed to get remote folder: {exc}")
            return self.exit_codes.ERROR_SCF_NO_REMOTE

        self.ctx.remote_for_dos = remote_folder
        self.ctx.fleurinp_base = self.ctx.scf_wc.outputs.fleurinp

        self.report(
            f"Obtained converged charge density from SCF (PK={self.ctx.scf_wc.pk})"
        )
        return

    def prepare_dos_from_remote(self):
        """Prepare DOS calculation using provided remote folder"""
        self.ctx.remote_for_dos = self.inputs.remote

        # Get fleurinp: prefer user-provided, otherwise extract from remote
        if "fleurinp" in self.inputs:
            self.ctx.fleurinp_base = self.inputs.fleurinp
            self.report("Using user-provided fleurinp for DOS calculation")
        else:
            try:
                self.ctx.fleurinp_base = get_fleurinp_from_remote_data(
                    self.inputs.remote
                )
                self.report("Extracted fleurinp from remote folder")
            except Exception as exc:
                self.report(f"Failed to extract fleurinp from remote: {exc}")
                return self.exit_codes.ERROR_INVALID_INPUT_FILE

        return

    def _get_remote_from_scf(self, scf_wc):
        """
        Extract remote_folder from the last FleurBaseWorkChain called by SCF workchain.
        Mimics logic from original BandDos workchain.
        """
        pk_last = 0
        last_base_wc = None

        # Find last FleurBaseWorkChain in called processes
        for called in scf_wc.called:
            if called.node_type == "process.workflow.workchain.WorkChainNode.":
                if called.process_class is FleurBaseWorkChain:
                    if called.pk > pk_last:
                        pk_last = called.pk
                        last_base_wc = called

        if last_base_wc is None:
            raise RuntimeError("No FleurBaseWorkChain found in SCF outputs")

        try:
            remote = last_base_wc.outputs.remote_folder
            return remote
        except (NotExistent, AttributeError) as exc:
            raise RuntimeError(
                f"Failed to get remote_folder from PK={last_base_wc.pk}: {exc}"
            )

    def run_dos_calculation(self):
        """Submit FLEUR calculation for DOS with custom k-mesh"""
        # Create modifier for DOS-specific settings
        fleurmode = FleurinpModifier(self.ctx.fleurinp_base)

        # Apply user-defined XML changes first
        inpxml_changes = self.ctx.wf_dict.get("inpxml_changes", [])
        if inpxml_changes:
            try:
                fleurmode.add_task_list(inpxml_changes)
            except (ValueError, TypeError) as exc:
                self.report(f"Failed to apply inpxml_changes: {exc}")
                return self.exit_codes.ERROR_CHANGING_FLEURINPUT_FAILED

        # Set DOS mode parameters
        fleurmode.set_inpchanges({
            "band": False,
            "dos": True,
            "minEnergy": self.ctx.wf_dict["emin"],
            "maxEnergy": self.ctx.wf_dict["emax"],
            "sigma": self.ctx.wf_dict["sigma"],
            "numberPoints": self.ctx.wf_dict["numberPoints"],
        })

        # XXX https://aiida-fleur.readthedocs.io/en/latest/module_guide/code.html#aiida_fleur.data.fleurinpmodifier.FleurinpModifier.set_kpointmesh
        fleurmode.set_kpointmesh(
            mesh=self.ctx.wf_dict["kpoints_mesh_dos"], switch=True
        )

        # Validate and freeze
        try:
            fleurmode.show(display=False, validate=True)
        except Exception as exc:
            self.report(
                f"Problematic XML snippet: {fleurmode.show(validate=False)}"
            )
            self.report(f"Input validation failed: {exc}")
            return self.exit_codes.ERROR_INVALID_INPUT_FILE

        fleurinp_dos = fleurmode.freeze()

        # Prepare inputs for FleurBaseWorkChain
        label = f"{self.ctx.label} - DOS calculation"

        # Prevent copying mixing history (clean DOS calculation)
        settings = {"remove_from_remotecopy_list": ["mixing_history*"]}

        inputs_builder = get_inputs_fleur(
            code=self.inputs.fleur,
            remote=self.ctx.remote_for_dos,
            fleurinp=fleurinp_dos,
            options=self.ctx.options,
            # XXX Should label be in metadata?
            label=label,
            settings=settings,
            add_comp_para=self.ctx.wf_dict["add_comp_para"],
        )

        future = self.submit(FleurBaseWorkChain, **inputs_builder)
        self.report(f"Submitted DOS calculation: PK={future.pk}")
        return ToContext(dos_calc=future)

    def parse_local_files(self):
        """Parse DOS data from Local.1 and Local.2 files"""
        if not self.ctx.dos_calc.is_finished_ok:
            self.report("DOS calculation failed")
            return self.exit_codes.ERROR_NO_LOCAL_FILES

        retrieved = self.ctx.dos_calc.outputs.retrieved
        available_files = retrieved.list_object_names()

        has_local1 = "Local.1" in available_files
        has_local2 = "Local.2" in available_files

        if not has_local1:
            self.report("ERROR: No Local.1 file found in retrieved folder")
            return self.exit_codes.ERROR_NO_LOCAL_FILES

        self.report("Found Local files: Local.1")
        if has_local2:
            self.report("Found Local.2 file ")

        try:
            dos_data = parse_local_dos(
                retrieved=retrieved,
                has_local1=has_local1,
                has_local2=has_local2,
            )

            self.ctx.dos_energy_ev = dos_data["energy_ev"]
            self.ctx.dos_total = dos_data["total_dos"]
            self.ctx.dos_spin_polarized = dos_data.get(
                "is_spin_polarized", False
            )

            # Store as XyData for provenance
            # TODO: replace with array data
            dos_xy = XyData()
            dos_xy.set_x(dos_data["energy_ev"], "energy", "eV")

            y_arrays = [dos_data["total_dos"]]
            y_names = ["total_dos"]
            y_units = ["states/eV"]

            if dos_data.get("is_spin_polarized"):
                self.ctx.dos_up = dos_data["spin_up"]
                self.ctx.dos_down = dos_data["spin_down"]
                y_arrays.extend([dos_data["spin_up"], dos_data["spin_down"]])
                y_names.extend(["spin_up", "spin_down"])
                y_units = ["states/eV"] * 3

            y_arrays = [np.array(i) for i in y_arrays]

            dos_xy.set_y(y_arrays, y_names, y_units)
            dos_xy.label = "dos_from_local_files"
            dos_xy.description = f'{self.ctx.label} DOS from Local files with {self.ctx.wf_dict["kpoints_mesh_dos"]} k-mesh'
            self.ctx.dos_xy = dos_xy

            self.report(
                f'Parsed DOS with {len(dos_data["energy_ev"])} energy points'
            )
            self.ctx.successful = True

        except Exception as exc:
            self.report(f"DOS parsing failed: {exc}")
            import traceback

            self.report(traceback.format_exc())
            return self.exit_codes.ERROR_DOS_PARSING_FAILED

    def calculate_seebeck_coefficient(self):
        """Calculate Seebeck coefficient using parsed DOS"""
        if not self.ctx.successful:
            self.report(
                "Skipping Seebeck calculation due to failed DOS parsing"
            )
            return

        # TODO check if works correctly
        try:
            # Get unit cell volume if structure provided
            volume_cm3 = None
            if "structure" in self.inputs:
                structure = self.inputs.structure
                volume_ang3 = structure.get_cell_volume()
                volume_cm3 = volume_ang3 * AngsCubeToCmCube  # angs**3 → cm**3
            elif hasattr(self.ctx, "fleurinp_base"):
                # Try to get structure from fleurinp
                try:
                    structure = (
                        self.ctx.fleurinp_base.get_structuredata_ncf()
                    )  # should return StructureData
                    volume_ang3 = structure.get_cell_volume()
                    volume_cm3 = (
                        volume_ang3 * AngsCubeToCmCube
                    )  # angs**3 → cm**3
                except Exception:
                    volume_cm3 = None

            # Prepare parameters
            params = self.ctx.seebeck_params
            if self.ctx.dos_spin_polarized:
                result1 = calculate_seebeck(
                    energy_ev=self.ctx.dos_energy_ev,
                    dos=self.ctx.dos_total,
                    T=params["temperature"],
                    doping_cm3=params["doping_cm3"],
                    fermi_energy_ev=params["fermi_energy_ev"],
                    volume_cm3=volume_cm3,
                    carrier_type=params["carrier_type"],
                )

                result2 = calculate_seebeck(
                    energy_ev=self.ctx.dos_energy_ev,
                    dos=self.ctx.dos_total,
                    T=params["temperature"],
                    doping_cm3=params["doping_cm3"],
                    fermi_energy_ev=params["fermi_energy_ev"],
                    volume_cm3=volume_cm3,
                    carrier_type=params["carrier_type"],
                )

                # TODO DOUBLE CHECK THIS. tests shows it gives reasonable results
                seebeck = (
                    result1["N"] * result1["seebeck_coefficient_uvk"]
                    + result2["N"] * result2["seebeck_coefficient_uvk"]
                ) / (result1["N"] + result2["N"])
                result = {
                    "seebeck_coefficient_uvk": seebeck,
                    "N": result1["N"] + result2["N"],
                }
            else:
                result = calculate_seebeck(
                    energy_ev=self.ctx.dos_energy_ev,
                    dos=self.ctx.dos_total,
                    T=params["temperature"],
                    doping_cm3=params["doping_cm3"],
                    fermi_energy_ev=params["fermi_energy_ev"],
                    volume_cm3=volume_cm3,
                    carrier_type=params["carrier_type"],
                )

            self.ctx.seebeck_result = result
            self.report(
                f"Calculated Seebeck coefficient: {result['seebeck_coefficient_uvk']:.2f} μV/K "
                f"at {params['temperature']} K"
            )

        except Exception as exc:
            self.report(f"Seebeck calculation failed: {exc}")
            import traceback

            self.report(traceback.format_exc())
            return self.exit_codes.ERROR_SEEBECK_CALCULATION_FAILED

    def return_results(self):
        """Return final results with full provenance"""
        output_dict = {
            "kpoints_mesh_dos": self.ctx.wf_dict["kpoints_mesh_dos"],
            "successful": self.ctx.successful,
            "scf_performed": self.ctx.scf_needed,
        }

        # Add SCF info if performed
        if self.ctx.scf_needed and hasattr(self.ctx, "scf_wc"):
            output_dict["scf_workchain_pk"] = self.ctx.scf_wc.pk
            output_dict["scf_converged"] = self.ctx.scf_wc.is_finished_ok

        # Add DOS calc info
        if hasattr(self.ctx, "dos_calc"):
            output_dict["dos_calculation_pk"] = self.ctx.dos_calc.pk

        # Add DOS metadata
        if hasattr(self.ctx, "dos_energy_ev"):
            output_dict.update({
                "energy_range_ev": [
                    float(self.ctx.dos_energy_ev.min()),
                    float(self.ctx.dos_energy_ev.max()),
                ],
                "dos_integral": float(
                    simpson(self.ctx.dos_total, self.ctx.dos_energy_ev)
                ),
                "spin_polarized": self.ctx.dos_spin_polarized,
            })

        # Add Seebeck results if available
        if hasattr(self.ctx, "seebeck_result"):
            output_dict.update({
                "seebeck_coefficient_uvk": self.ctx.seebeck_result[
                    "seebeck_coefficient_uvk"
                ],
                "temperature_k": self.ctx.seebeck_params["temperature"],
                "carrier_type": self.ctx.seebeck_params["carrier_type"],
                "doping_cm3": self.ctx.seebeck_params["doping_cm3"],
            })

        self.out("output_dos_local_wc_para", Dict(output_dict).store())

        # Output DOS data
        if hasattr(self.ctx, "dos_xy"):
            if not self.ctx.dos_xy.is_stored:
                self.ctx.dos_xy.store()
            self.out("output_dos_xy", self.ctx.dos_xy)

        # Output Seebeck result
        if hasattr(self.ctx, "seebeck_result"):
            self.out("output_seebeck", Dict(self.ctx.seebeck_result).store())

        # Expose DOS calculation outputs
        if hasattr(self.ctx, "dos_calc") and self.ctx.dos_calc.is_finished_ok:
            self.out_many(
                self.exposed_outputs(
                    self.ctx.dos_calc, FleurBaseWorkChain, namespace="dos_calc"
                )
            )

        status = "successfully" if self.ctx.successful else "with failures"
        self.report(f"FleurDOSLocalWorkChain completed {status}")
        return


def read_local_file(retrieved, filename):
    """Read Local.X file and extract energy and total DOS columns"""
    content = retrieved.get_object_content(filename)
    lines = content.strip().split("\n")

    # Skip comment/header lines (usually start with '#')
    data_lines = [
        line
        for line in lines
        if not line.strip().startswith("#") and line.strip()
    ]

    if not data_lines:
        raise ValueError(
            f"File {filename} appears empty or contains only comments"
        )

    # Parse columns (energy in eV, DOS in states/eV)
    energies = []
    total_dos = []

    for line in data_lines:
        parts = re.split(r"\s+", line.strip())
        if len(parts) >= 2:
            try:
                e = float(parts[0])
                d = float(parts[1])
                energies.append(e)
                total_dos.append(d)
            except ValueError:
                continue  # Skip malformed lines

    if not energies:
        raise ValueError(f"No valid data parsed from {filename}")

    return np.array(energies), np.array(total_dos)


def parse_local_dos(retrieved, has_local1, has_local2):
    """
    Parse DOS from FLEUR's Local.1 and Local.2 files.

    Format of Local.X files:
    Column 1: energy (eV) relative to Fermi energy
    Column 2: total DOS (states/eV)
    Further columns: atom- and orbital-resolved DOS

    Returns:
        Dict with keys:
        - energy_ev: numpy array of energies in eV
        - total_dos: numpy array of total DOS
    """

    # Parse files based on availability
    if has_local1 and has_local2:
        # Spin-polarized calculation
        e_up, dos_up = read_local_file(retrieved, "Local.1")
        e_dn, dos_dn = read_local_file(retrieved, "Local.2")

        # Verify energy grids match
        if len(e_up) != len(e_dn) or not np.allclose(e_up, e_dn, atol=1e-6):
            raise ValueError(
                "Energy grids in Local.1 and Local.2 do not match"
            )

        # Total DOS = spin_up + spin_down
        total_dos = dos_up + dos_dn

        return {
            "energy_ev": e_up,
            "total_dos": total_dos,
            "spin_up": dos_up,
            "spin_down": dos_dn,
            "is_spin_polarized": True,
        }

    elif has_local1:
        # Non-spin-polarized calculation
        energy, total_dos = read_local_file(retrieved, "Local.1")

        return {
            "energy_ev": energy,
            "total_dos": total_dos,
            "is_spin_polarized": False,
        }

    else:
        raise ValueError("No Local files available for parsing")


def calculate_seebeck(
    energy_ev,
    dos,
    T=5,
    doping_cm3=5e18,
    fermi_energy_ev=0.0,
    volume_cm3=1e-24,
    carrier_type="hole",
):
    """
    Calculate Seebeck coefficient based on https://arxiv.org/pdf/1708.01591 thermodynamic approach.
    """
    kb = const.Boltzmann / const.electron_volt

    # Determine chemical potential mu
    if doping_cm3 is not None:
        if volume_cm3 is None:
            raise ValueError(
                "Volume (cm^3) required when specifying doping concentration"
            )

        carriers_per_unit_cell = doping_cm3 * volume_cm3
        is_p_type = carrier_type == "hole"

        mask_0k = energy_ev <= 0.0
        N_0k = simpson(dos[mask_0k], energy_ev[mask_0k])

        if is_p_type:
            N_target = N_0k - carriers_per_unit_cell
        else:
            N_target = N_0k + carriers_per_unit_cell

        # define them here since it's much easier to pass it to root_scalar
        def fermi_dirac_safe(energy_ev, mu_ev, temperature_k):
            x = -(energy_ev - mu_ev) / (kb * temperature_k)
            return expit(x)

        def charge_neutrality(mu):
            f = fermi_dirac_safe(energy_ev, mu, T)
            N_T = simpson(dos * f, energy_ev)
            return N_T - N_target

        sol = root_scalar(
            charge_neutrality, bracket=[-0.5, 0.5], method="bisect", xtol=1e-8
        )
        if not sol.converged:
            raise RuntimeError("Failed to converge chemical potential")
        mu_ev = sol.root
    else:
        # Not sure if this is work's correctly
        mu_ev = fermi_energy_ev

    # Fermi-Dirac distribution
    x = (energy_ev - mu_ev) / (kb * T)
    f = expit(x)

    # Compute integrals
    f1f = f * (1 - f)
    numerator = simpson(dos * f1f * (energy_ev - mu_ev), energy_ev)
    denominator = simpson(dos * f1f, energy_ev)

    if abs(denominator) < 1e-20:
        raise ValueError(
            "Denominator integral too small - check DOS and temperature"
        )

    alpha_vk = -numerator / (denominator * T)
    alpha_uvk = alpha_vk * 1e6  # V/K to uV/K

    if carrier_type == "hole":
        alpha_uvk = abs(alpha_uvk)
    else:
        alpha_uvk = -abs(alpha_uvk)

    return {"seebeck_coefficient_uvk": alpha_uvk, "N": N_0k}


def example_submission_scf_then_dos():
    """
    Example 1: Full workflow with SCF convergence first
    """
    from aiida import load_profile
    from aiida.orm import Dict

    load_profile()

    fleur_code = load_code("fleur")
    inpgen_code = load_code("inpgen")
    structure = load_node(280548)  # PbTe

    # SCF parameters (coarse k-mesh for convergence)
    wf_para_scf = Dict(
        dict={
            "fleur_runmax": 5,
            "density_converged": 1.0e-6,
            "mode": "density",
            "itmax_per_run": 50,
        }
    )

    # DOS parameters (fine 48x48x48 mesh)
    wf_para_dos = Dict(
        dict={
            "kpoints_mesh_dos": [48, 48, 48],
            "sigma": 0.002,
            "emin": -2.0,
            "emax": 2.0,
        }
    )

    # Seebeck parameters
    seebeck_params = Dict(
        dict={
            "temperature": 5.0,
            "carrier_type": "hole",
            "doping_cm3": 5e18,  # cm^-3
        }
    )

    # Submit workflow with SCF namespace
    inputs = {
        "scf": {
            "wf_parameters": wf_para_scf,
            "structure": structure,
            "inpgen": inpgen_code,
            "fleur": fleur_code,
        },
        "fleur": fleur_code,
        "wf_parameters": wf_para_dos,
        "seebeck_parameters": seebeck_params,
        "structure": structure,  # for volume calculation in Seebeck
    }

    from aiida.engine import run

    workchain = run(FleurDOSLocalWorkChain, **inputs)
    return workchain


def example_from_remote():
    """
    Example 2: DOS calculation from existing remote folder
    """
    from aiida import load_profile
    from aiida.engine import run

    load_profile()

    fleur_code = load_code("fleur")
    remote = load_node(280879)

    wf_para_dos = Dict(
        dict={
            "kpoints_mesh_dos": [48, 48, 48],
            "sigma": 0.002,
            "emin": -2.0,
            "emax": 2.0,
        }
    )

    # Seebeck parameters
    seebeck_params = Dict(
        dict={
            "temperature": 5.0,
            "carrier_type": "hole",
            "doping_cm3": 5e18,  # cm^-3
        }
    )

    inputs = {
        "fleur": fleur_code,
        "remote": remote,
        "wf_parameters": wf_para_dos,
        "seebeck_parameters": seebeck_params,
    }

    workchain = run(FleurDOSLocalWorkChain, **inputs)
    return workchain


if __name__ == "__main__":
    example_submission_scf_then_dos()
