"""Map ABACUS force rows using the actual submitted STRU, not species guesses."""

import numpy as np
import re


def scf_has_converged(log_content):
    """Require convergence in the last ABACUS session, not an earlier restart."""
    session = re.split(r"(?m)^[ \t]*ABACUS v[^\n]*$", log_content)[-1]
    statuses = list(
        re.finditer(
            r"#SCF IS CONVERGED#|#SCF IS NOT CONVERGED#|convergence (?:has |is )?not (?:been )?achieved",
            session,
            re.IGNORECASE,
        )
    )
    return bool(statuses and statuses[-1].group().upper() == "#SCF IS CONVERGED#")


def read_scf_log(calculation):
    """Read either flat yascheduler retrieval or the native OUT.<suffix> layout."""
    repository = calculation.outputs.retrieved.base.repository
    suffix = (
        calculation.inputs.parameters.get_dict().get("input", {}).get("suffix", "aiida")
    )
    for filename in ("running_scf.log", f"OUT.{suffix}/running_scf.log"):
        try:
            return repository.get_object_content(filename)
        except FileNotFoundError:
            continue
    raise FileNotFoundError("No retrieved running_scf.log in flat or native layout")


def restore_force_order(structure, forces, stru_content):
    """Return forces in StructureData order and the STRU-to-structure permutation.

    The mapping is checked against the submitted cell, kinds and coordinates.
    Unknown coordinate conventions and ambiguous mappings fail explicitly.
    """
    lines = [
        line.split("#")[0].split("//")[0].strip() for line in stru_content.splitlines()
    ]
    lines = [line for line in lines if line]
    scale = float(lines[lines.index("LATTICE_CONSTANT") + 1]) * 0.529177210903
    start = lines.index("LATTICE_VECTORS") + 1
    cell = (
        np.array(
            [[float(x) for x in line.split()[:3]] for line in lines[start : start + 3]]
        )
        * scale
    )
    if not np.allclose(cell, structure.cell, atol=1e-7, rtol=0):
        raise ValueError("Submitted STRU cell differs from the force input structure")
    cursor = lines.index("ATOMIC_POSITIONS") + 1
    convention = lines[cursor].lower()
    if convention not in ("cartesian", "direct"):
        raise ValueError(f"Unsupported STRU coordinate convention: {convention}")
    cursor += 1
    nsites = len(structure.sites)
    array = np.asarray(forces, dtype=float)
    if array.shape != (nsites, 3) or not np.isfinite(array).all():
        raise ValueError(f"Expected {nsites} finite three-component force rows")
    permutation = []
    while len(permutation) < nsites:
        name = lines[cursor]
        count = int(lines[cursor + 2])
        cursor += 3
        if count <= 0 or len(permutation) + count > nsites:
            raise ValueError("Invalid atom count in submitted STRU")
        for line in lines[cursor : cursor + count]:
            position = np.array([float(x) for x in line.split()[:3]])
            position = position @ cell if convention == "direct" else position * scale
            matches = [
                index
                for index, site in enumerate(structure.sites)
                if site.kind_name == name
                and np.allclose(site.position, position, atol=1e-7, rtol=0)
            ]
            if len(matches) != 1 or matches[0] in permutation:
                raise ValueError(
                    "STRU atoms cannot be matched uniquely to the input structure"
                )
            permutation.append(matches[0])
        cursor += count
    if sorted(permutation) != list(range(nsites)):
        raise ValueError(
            "Submitted STRU does not contain every input atom exactly once"
        )
    restored = np.empty_like(array)
    restored[permutation] = array
    return restored.tolist(), permutation
