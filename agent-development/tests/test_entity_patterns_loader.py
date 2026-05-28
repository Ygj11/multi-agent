from pathlib import Path

import pytest

from app.query.entity_extractor import EntityPatternLoader


def test_entity_patterns_loader_reads_project_yaml():
    patterns = EntityPatternLoader(Path("app/query/entity_patterns.yaml")).load()

    by_type = {item.entity_type: item for item in patterns}
    assert "request_id" in by_type
    assert "apply_seq" in by_type
    assert "endorseType" in by_type
    assert "interface_name" in by_type
    assert by_type["phone_number"].sensitive is True
    assert by_type["error_code"].confidence == 0.9
    assert by_type["interface_name"].keyword_allowlist


def test_entity_patterns_loader_missing_required_field_fails(tmp_path):
    path = tmp_path / "entity_patterns.yaml"
    path.write_text(
        """
version: "1.0.0"
patterns:
  - entity_type: request_id
    regex:
      - "\\bREQ[_-]?\\d+\\b"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required fields"):
        EntityPatternLoader(path).load()


def test_entity_patterns_loader_invalid_regex_fails(tmp_path):
    path = tmp_path / "entity_patterns.yaml"
    path.write_text(
        """
version: "1.0.0"
patterns:
  - entity_type: broken
    description: broken regex
    regex:
      - "["
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid regex"):
        EntityPatternLoader(path).load()
