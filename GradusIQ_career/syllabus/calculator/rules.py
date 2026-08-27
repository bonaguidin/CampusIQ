"""Deterministic execution of REPLACEMENT rules; explicit refusal of the rest.

Only REPLACEMENT rules are executed in Phase 6, and only in the narrow form
the Phase 1 schema actually represents: "if source's score is higher than
target's score, target's effective score becomes source's score." That
semantic is inherent to GradingRuleType.REPLACEMENT itself (see
GradingRule's docstring in syllabus/models.py) -- not something parsed out
of the free-text `condition` field.

`condition` IS still consulted, but only as a narrow, conservative sanity
check: it must look like a bare "A > B" comparison (see
looks_like_simple_greater_than) or be absent entirely. A condition using
any other comparison operator, a boolean combinator, or free-form prose is
rejected via UnsupportedRuleConditionError -- it may describe a genuinely
different rule shape this module does not implement, and NEVER eval()'d or
exec()'d to find out.

DROP, CURVE, EXTRA_CREDIT, LATE_WORK, MAKEUP, and OTHER rules are never
executed: the Phase 1 schema has no field capturing what a DROP rule drops
FROM (e.g. the full list of scores "drop the lowest quiz" would need to
compare), and the rest have no formula field at all -- see
reconciliation.py's _is_rule_deterministic, whose non-determinism finding
should already have kept a model with an unresolved rule of this kind out
of ACCEPTED. Encountering one here anyway (a defensively-handled
possibility) produces a warning, not a crash: it does not block computing
whatever the rest of the model DOES support.
"""

import re

from GradusIQ_career.syllabus.calculator.models import (
    AppliedRule,
    CalculationComponent,
    UnsupportedRuleConditionError,
)
from GradusIQ_career.syllabus.models import GradeModel, GradingRule, GradingRuleType

# Exactly one '>' and no other comparison operator or boolean keyword.
_NO_OTHER_OPERATORS_RE = re.compile(r"^[^<>=]*>[^<>=]*$")
_BOOLEAN_KEYWORD_RE = re.compile(r"\b(and|or|not)\b", re.IGNORECASE)


def looks_like_simple_greater_than(condition: str | None) -> bool:
    """True for None (no condition text supplied -- REPLACEMENT's fixed
    semantic still applies) or a bare "A > B" comparison. False for
    anything using >=, <=, <, ==, a boolean combinator, or prose that adds
    an unmodeled qualifier this module cannot safely ignore.
    """
    if condition is None:
        return True
    stripped = condition.strip()
    if not stripped:
        return True
    if _BOOLEAN_KEYWORD_RE.search(stripped):
        return False
    return bool(_NO_OTHER_OPERATORS_RE.match(stripped))


def is_rule_supported(rule: GradingRule) -> bool:
    """Whether Phase 6 can execute this rule at all (independent of
    whether the referenced components' scores are actually known yet --
    see rules.apply_deterministic_rules for that).
    """
    return rule.rule_type == GradingRuleType.REPLACEMENT and looks_like_simple_greater_than(rule.condition)


def _find(components: list[CalculationComponent], name: str) -> CalculationComponent | None:
    normalized = " ".join(name.lower().split())
    for component in components:
        if " ".join(component.name.lower().split()) == normalized:
            return component
    return None


def apply_deterministic_rules(
    grade_model: GradeModel,
    components: list[CalculationComponent],
) -> tuple[list[CalculationComponent], list[AppliedRule], list[str]]:
    """Apply every supported rule, in GradeModel.rules order (an explicit,
    stable order -- never re-sorted or reinterpreted). Returns new
    component objects (originals are never mutated), the rules actually
    applied, and warnings for anything skipped.

    Only REPLACEMENT is executed. See module docstring for DROP/others.
    """
    working = list(components)
    applied: list[AppliedRule] = []
    warnings: list[str] = []

    for rule in grade_model.rules:
        if rule.rule_type != GradingRuleType.REPLACEMENT:
            warnings.append(
                f"{rule.rule_type.value} rule ('{rule.description}') cannot be executed deterministically "
                "with the current syllabus data; affected scores are used unmodified"
            )
            continue
        if not looks_like_simple_greater_than(rule.condition):
            raise UnsupportedRuleConditionError(
                f"replacement rule condition '{rule.condition}' is not a recognized simple comparison; "
                "refusing to guess its meaning"
            )
        if rule.source is None or rule.target is None:
            warnings.append(
                f"replacement rule ('{rule.description}') is missing source or target and cannot be "
                "executed deterministically; scores are used unmodified"
            )
            continue

        source = _find(working, rule.source)
        target = _find(working, rule.target)
        if source is None or target is None:
            warnings.append(
                f"replacement rule references '{rule.source}' -> '{rule.target}', which do not both "
                "match a known category/assessment; scores are used unmodified"
            )
            continue
        if source.effective_score is None or target.effective_score is None:
            # Not enough is known yet to decide whether the rule triggers.
            # Not an error -- this is completely normal mid-course.
            continue

        changed = source.effective_score > target.effective_score
        if changed:
            new_target = target.model_copy(
                update={
                    "effective_score": source.effective_score,
                    "contribution": (
                        source.effective_score * target.weight_percent / 100
                        if target.weight_percent is not None
                        else None
                    ),
                }
            )
            working = [new_target if c is target else c for c in working]

        applied.append(
            AppliedRule(
                rule_type=rule.rule_type,
                source=rule.source,
                target=rule.target,
                changed_calculation=changed,
                description=rule.description,
            )
        )

    return working, applied, warnings
