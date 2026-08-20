"""Tests for Schema and Migration Script Generator."""


from epires_core.schema import generate_migration_script_template, get_canonical_schema


def test_canonical_schema():
    schema = get_canonical_schema()
    assert schema["title"] == "Epires Canonical Research Graph Schema"
    assert "EvidenceLevel" in schema["enums"]
    assert "hypothesis_format" in schema
    assert "evidence_format" in schema
    assert "python_quickstart" in schema


def test_migration_script_template():
    code = generate_migration_script_template(source_file="docs/my_notes.md")
    assert "docs/my_notes.md" in code
    assert "EpiresStore" in code
    assert "store.bulk_import" in code
