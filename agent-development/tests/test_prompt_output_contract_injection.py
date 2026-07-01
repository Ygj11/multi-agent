from app.prompts.loader import PromptLoader


def test_prompt_loader_injects_task_completion_output_contract():
    rendered = PromptLoader().render_scene_system("task_completion_verifier")

    assert "Output contract: TaskCompletionLLMOutput" in rendered
    assert "repair_plan" in rendered
    assert "PASS" in rendered
    assert "CONTINUE" in rendered


def test_prompt_loader_injects_intent_output_contract_without_entities():
    rendered = PromptLoader().render_scene_system("intent_recognition")

    assert "Output contract: IntentRecognitionLLMOutput" in rendered
    contract_section = rendered.split("Output contract: IntentRecognitionLLMOutput", 1)[1]
    assert "intent" in contract_section
    assert "sub_intent" in contract_section
    assert "entities" not in contract_section


def test_prompt_loader_does_not_inject_large_contract_for_text_scene():
    rendered = PromptLoader().render_scene_system("memory_summary")

    assert "Output contract:" not in rendered


def test_prompt_loader_allows_explicit_contract_override():
    rendered = PromptLoader().render_scene_system("task_completion_verifier", output_contract="CUSTOM CONTRACT")

    assert "CUSTOM CONTRACT" in rendered
    assert "Output contract: TaskCompletionLLMOutput" not in rendered
