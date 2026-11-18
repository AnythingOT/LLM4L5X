import pytest

from core.catalog import default_catalog, load_catalog


def test_core_set_present():
    cat = default_catalog()
    for name in "XIC XIO OTE OTL OTU ONS TON TOF CTU CTD MOV ADD SUB MUL DIV CLR COP EQU NEQ GRT LES GEQ LEQ".split():
        assert name in cat, name


def test_v36_renamed_mnemonics():
    """Rockwell renamed these in Logix Designer v36 (IEC 61131-3 / PLCopen names)."""
    cat = default_catalog()
    pairs = {"EQU": "EQ", "NEQ": "NE", "GRT": "GT", "LES": "LT", "GEQ": "GE", "LEQ": "LE",
             "LIM": "LIMIT", "MOV": "MOVE"}
    for old, new in pairs.items():
        o, n = cat.get(old), cat.get(new)
        assert o.max_version == 35 and o.renamed_to == new, old
        assert n.min_version == 36 and len(n.operands) == len(o.operands), new
        assert o.available_in(35) and not o.available_in(36)
        assert n.available_in(36) and not n.available_in(35)


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
