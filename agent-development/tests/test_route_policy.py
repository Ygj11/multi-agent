from app.runtime.route_policy import RoutePolicy
from app.schemas.enums.graph import TaskCompletionRoute
from app.verification.schemas import VerificationResult


def test_route_policy_entry_and_clarification_routes():
    assert RoutePolicy.route_entry({"approval_resume": True}) == "resume"
    assert RoutePolicy.route_entry({}) == "normal"
    assert RoutePolicy.route_clarification({"need_clarification": True}) == "clarify"
    assert RoutePolicy.route_clarification({"need_clarification": False}) == "continue"


def test_route_policy_approval_routes():
    assert RoutePolicy.route_approval_required({"approval_required": True}) == "required"
    assert RoutePolicy.route_approval_required({"approval_required": False}) == "not_required"
    assert RoutePolicy.route_after_create_approval({"manual_intervention_required": True}) == "manual"
    assert RoutePolicy.route_after_create_approval({"manual_intervention_required": False}) == "submit"


def test_route_policy_verification_routes():
    passed = VerificationResult(passed=True, stage="pre_answer", verifier_name="test", action="allow")
    retry = VerificationResult(passed=False, stage="pre_answer", verifier_name="test", action="retry")

    assert RoutePolicy.route_verification({"pre_answer_verification_result": passed.model_dump(), "retry_count": 0}) == "passed"
    assert RoutePolicy.route_verification({"pre_answer_verification_result": retry.model_dump(), "retry_count": 0}) == "retry"
    assert RoutePolicy.route_verification({"pre_answer_verification_result": retry.model_dump(), "retry_count": 1}) == "fallback"


def test_route_policy_task_completion_does_not_repair_invalid_status_case():
    assert (
        RoutePolicy.route_task_completion({"task_completion_verification_result": {"status": "pass"}})
        is TaskCompletionRoute.FAILED
    )
    assert (
        RoutePolicy.route_task_completion({"task_completion_verification_result": {"status": "UNKNOWN"}})
        is TaskCompletionRoute.FAILED
    )
