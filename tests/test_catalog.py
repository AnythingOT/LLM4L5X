import pytest

from core.catalog import default_catalog, load_catalog


def test_core_set_present():
    cat = default_catalog()
    for name in "XIC XIO OTE OTL OTU ONS TON TOF CTU CTD MOV ADD SUB MUL DIV CLR COP EQU NEQ GRT LES GEQ LEQ".split():
        assert name in cat, name


def test_old_repo_mnemonics_are_not_valid():
    cat = default_catalog()
    for bad in ("EQ", "NE", "GT", "LT", "GE", "LE"):
        assert bad not in cat


def test_lookup_case_insensitive_and_kinds():
    cat = default_catalog()
    assert cat.get("xic").is_input
    assert cat.get("OTE").is_output
    assert cat.get("ONS").is_input
    assert [o.role for o in cat.get("TON").operands] == ["struct", "display", "display"]


def test_bad_yaml_rejected():
    with pytest.raises(ValueError):
        load_catalog("FOO:\n  kind: sideways\n  operands: []\n")
    with pytest.raises(ValueError):
        load_catalog("FOO:\n  kind: input\n  operands:\n    - {name: a, type: BOOL, role: maybe}\n")
