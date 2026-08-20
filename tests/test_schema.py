from epires_core.models import EvidenceLevel, HypothesisStatus, RelationType, SourceConfidence
from epires_core.schema import generate_migration_script_template, get_canonical_schema


def test_canonical_schema():
    schema = get_canonical_schema()
    assert schema["title"] == "Epires Canonical Research Graph Schema"

    # Enums must match models exactly
    assert set(schema["enums"]["EvidenceLevel"]) == {e.value for e in EvidenceLevel}
    assert set(schema["enums"]["HypothesisStatus"]) == {e.value for e in HypothesisStatus}
    assert set(schema["enums"]["SourceConfidence"]) == {e.value for e in SourceConfidence}
    assert set(schema["enums"]["RelationType"]) == {e.value for e in RelationType}

    assert "hypothesis_format" in schema
    assert "evidence_format" in schema
    assert "python_quickstart" in schema

    # Quickstart code snippet must be valid Python code
    compile(schema["python_quickstart"], "<quickstart>", "exec")


def test_migration_script_template():
    code = generate_migration_script_template(source_file="docs/my_notes.md")
    assert "docs/my_notes.md" in code
    assert "EpiresStore" in code
    assert "store.bulk_import" in code

    # Generated template must compile cleanly
    compile(code, "<migration_template>", "exec")
