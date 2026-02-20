"""Tests for customer interaction feedback generation."""

from src.simulation.customer_feedback import CustomerFeedbackGenerator


def test_feedback_generator_returns_template_feedback_for_failure():
    generator = CustomerFeedbackGenerator(use_llm=False)
    feedback = generator.render_feedback(
        actor_type="founder",
        actor_id="founder_001",
        interaction={
            "step_id": "visit_to_signup",
            "outcome": "failed",
            "reason_code": "founder_no_signup",
            "score_snapshot": {"signup_prob": 0.12},
        },
    )

    assert feedback["source"] == "template"
    assert "Signup aborted" in feedback["message"]
    assert feedback["category"] == "signup_conversion"
    assert feedback["action_hint"]
    assert feedback["contract_version"] == 1


def test_feedback_generator_handles_signup_incomplete_reason_code():
    generator = CustomerFeedbackGenerator(use_llm=False)
    feedback = generator.render_feedback(
        actor_type="vc",
        actor_id="vc_001",
        interaction={
            "step_id": "visit_to_signup",
            "outcome": "failed",
            "reason_code": "vc_signup_incomplete_profile",
            "score_snapshot": {"missing_required_fields": ["thesis_sectors"]},
        },
    )

    assert feedback["source"] == "template"
    assert "required VC profile fields were missing" in feedback["message"]
    assert "thesis_sectors" in feedback["message"]
    assert feedback["category"] == "signup_validation"
    assert feedback["contract_version"] == 1


def test_feedback_generator_falls_back_to_template_in_mock_mode():
    generator = CustomerFeedbackGenerator(
        use_llm=True,
        llm_steps=["matched_to_interested"],
    )
    feedback = generator.render_feedback(
        actor_type="vc",
        actor_id="vc_001",
        interaction={
            "step_id": "matched_to_interested",
            "outcome": "failed",
            "reason_code": "vc_not_interested",
            "score_snapshot": {"interest_prob": 0.31},
        },
    )

    # In local/mock runs we keep deterministic template feedback.
    assert generator.llm_active is False
    assert feedback["source"] == "template"
    assert "Interest step aborted" in feedback["message"]
    assert feedback["category"] == "interest_gate"
    assert feedback["contract_version"] == 1
