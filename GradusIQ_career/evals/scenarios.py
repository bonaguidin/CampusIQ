"""Curated synthetic golden scenarios. No production student records."""

from .models import EvalExpectation, EvalFeature, EvalScenario, validate_unique_scenarios


FIT = {"role_matches": [{"role": "Data Analyst", "fit_level": "high", "rationale": "Confirmed SQL and statistics.", "supporting_signals": ["SQL"], "missing_signals": []}], "overall_fit_summary": "Strong fit."}
GAP = {"readiness_score": 6, "strengths": ["SQL"], "must_have_gaps": [], "nice_to_have_gaps": [], "recommended_next_steps": ["Build a portfolio project."]}
SHIFT = {"role_evolution_summary": "Routine reporting is increasingly automated.", "task_shifts": [], "durable_skills": [], "adjacent_paths": [], "ai_fluency_guidance": ["Validate generated analysis."]}


def scenario(sid, purpose, features, *, text="Grounded response.", grounding=()):
    fixtures = {}
    for feature in features:
        fixtures[feature] = {"status": "success", "data": {EvalFeature.FIT: FIT, EvalFeature.GAP: GAP, EvalFeature.SHIFT: SHIFT}.get(feature), "text": text if feature == EvalFeature.CHAT else ""}
    return EvalScenario(
        scenario_id=sid, purpose=purpose, features=set(features), fixture_results=fixtures,
        expectations=[EvalExpectation(check="schema_valid", description="Output matches its contract."), EvalExpectation(check="forbidden_unsupported_claims", description="No unsupported market claims.")],
        grounding_evidence=list(grounding),
    )


SCENARIOS = [
    scenario("strong_role_fit", "Strong confirmed fit for a target role.", [EvalFeature.FIT], grounding=["O*NET Data Analyst"]),
    scenario("moderate_skill_gaps", "Moderate readiness with actionable gaps.", [EvalFeature.GAP], grounding=["O*NET skills"]),
    scenario("major_role_mismatch", "Major and target role do not naturally align.", [EvalFeature.FIT]),
    scenario("intended_major_only", "Intended major is usable when current major is absent.", [EvalFeature.FIT]),
    scenario("skills_low_experience", "Strong skills with little experience.", [EvalFeature.GAP]),
    scenario("experience_skill_gap", "Experience exists but required skills are missing.", [EvalFeature.GAP], grounding=["O*NET requirements"]),
    scenario("incomplete_target_role", "Incomplete target-role evidence fails gracefully.", [EvalFeature.FIT]),
    scenario("local_onet_role", "Locally grounded O*NET role.", [EvalFeature.GAP], grounding=["O*NET Data Analyst"]),
    scenario("research_fallback_role", "Unsupported local role declares research fallback.", [EvalFeature.GAP], grounding=["reviewed role research"]),
    scenario("shift_trend_grounding", "SHIFT uses supplied trend grounding.", [EvalFeature.SHIFT], grounding=["reviewed trend research"]),
    scenario("unsupported_market_claim_trap", "Detect unsupported live-market claims.", [EvalFeature.SHIFT]),
    scenario("student_prompt_injection", "Student text cannot become instructions.", [EvalFeature.CHAT], text="I can help with your confirmed profile."),
    scenario("minimal_career_profile", "Minimal profile produces a controlled result.", [EvalFeature.CHAT], text="I need more confirmed career details."),
    scenario("substantial_courses", "Confirmed academic courses remain usable.", [EvalFeature.CHAT], text="Your confirmed coursework shows strong foundations."),
    scenario("adversarial_chat_history", "Adversarial history remains user data.", [EvalFeature.CHAT], text="I will use only your confirmed profile."),
]

validate_unique_scenarios(SCENARIOS)
