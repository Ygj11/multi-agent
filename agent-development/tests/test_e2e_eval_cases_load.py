from app.evaluation.e2e.runner import DynamicE2EEvalRunner


def test_dynamic_e2e_eval_cases_load_and_ids_are_unique():
    suites = DynamicE2EEvalRunner().load_suites()

    assert {suite.suite for suite in suites} >= {"dynamic_smoke"}
    all_case_ids = [case.case_id for suite in suites for case in suite.cases]
    assert len(all_case_ids) == len(set(all_case_ids))


def test_dynamic_e2e_eval_case_declares_real_llm_mode():
    suite = DynamicE2EEvalRunner().load_suites()[0]
    case = suite.cases[0]

    assert case.llm_mode == "real"
    assert case.transport in {"orchestrator", "http"}
    assert case.expected.answer_must_include
