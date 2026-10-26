import pytest
from terrain_packing_space import require_capacity


def test_split_spool_does_not_charge_two_payloads_to_final_drive():
    assert require_capacity({'C':24,'D':24},'C','D',3,reserve=20,margin=1)=={'C':24,'D':24}
    with pytest.raises(OSError):require_capacity({'C':24},'C','C',3,reserve=20,margin=1)


def test_free_space_cannot_be_pooled_across_volumes():
    with pytest.raises(OSError):require_capacity({'C':100,'D':22},'C','D',3,reserve=20,margin=1)
    with pytest.raises(OSError):require_capacity({'C':22,'D':100},'C','D',3,reserve=20,margin=1)
