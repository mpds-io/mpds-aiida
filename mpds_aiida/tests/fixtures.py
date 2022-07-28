
import pytest


@pytest.fixture
def test_basis(aiida_profile):
    from aiida_crystal_dft.data.basis_family import CrystalBasisFamilyData
    basis_family, _ = CrystalBasisFamilyData.get_or_create('STO-3G')
    return basis_family
