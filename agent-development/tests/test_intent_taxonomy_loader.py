import pytest

from app.query.intent_taxonomy_loader import IntentTaxonomyLoader
from app.schemas.intent_taxonomy import IntentTaxonomy


def test_intent_taxonomy_loader_loads_default_taxonomy():
    loader = IntentTaxonomyLoader()

    taxonomy = loader.load(force_reload=True)

    assert "troubleshooting" in taxonomy.allowed_intents()
    assert "pos_query" in taxonomy.allowed_intents()
    assert loader.is_allowed_sub_intent("troubleshooting", "endo_completion_aftercare")
    assert not loader.is_allowed_sub_intent("pos_query", "endo_completion_aftercare")


def test_intent_taxonomy_loader_candidate_sub_intents_are_grouped():
    loader = IntentTaxonomyLoader()

    candidates = loader.list_candidate_sub_intents()

    assert "signature_error" in candidates["troubleshooting"]
    assert "pos_available_items" in candidates["pos_query"]
    assert "internal_log_analysis" not in candidates["troubleshooting"]


def test_intent_taxonomy_rejects_empty_intents():
    with pytest.raises(ValueError, match="at least one intent"):
        IntentTaxonomy(intents={})


def test_intent_taxonomy_loader_rejects_non_mapping_root(tmp_path):
    taxonomy_path = tmp_path / "intent_taxonomy.yaml"
    taxonomy_path.write_text("- bad\n", encoding="utf-8")

    with pytest.raises(ValueError, match="root must be a mapping"):
        IntentTaxonomyLoader(taxonomy_path).load(force_reload=True)


def test_intent_taxonomy_loader_loads_custom_file(tmp_path):
    taxonomy_path = tmp_path / "intent_taxonomy.yaml"
    taxonomy_path.write_text(
        """
intents:
  demo:
    display_name: Demo
    description: Demo intent
    sub_intents:
      demo_sub:
        display_name: Demo Sub
        description: Demo sub intent
""",
        encoding="utf-8",
    )

    loader = IntentTaxonomyLoader(taxonomy_path)

    assert loader.list_allowed_intents() == ["demo"]
    assert loader.list_candidate_sub_intents() == {"demo": ["demo_sub"]}
