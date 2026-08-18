from GradusIQ_career.features.fit import _resolve_major


def test_empty_current_major_with_intended_and_switching_flag_is_a_declare_not_a_switch():
    # The bug: a student with no major_current on file who names an intended
    # major has nothing to switch FROM. Whatever a UI checkbox claims, this is
    # a first-time declaration, not a switch -- _resolve_major takes no
    # checkbox input at all, so this must hold unconditionally.
    student = {"major_current": "", "major_intended": "Computer Science"}
    assert _resolve_major(student) == ("Computer Science", "declare")


def test_missing_current_major_key_with_intended_is_also_a_declare():
    student = {"major_intended": "Computer Science"}
    assert _resolve_major(student) == ("Computer Science", "declare")


def test_empty_current_and_no_intended_major_stays_empty_and_staying():
    student = {"major_current": "", "major_intended": ""}
    assert _resolve_major(student) == ("", "staying")


def test_empty_current_and_na_intended_stays_empty_and_staying():
    student = {"major_current": "", "major_intended": "N/A"}
    assert _resolve_major(student) == ("", "staying")


def test_real_current_and_distinct_intended_major_is_switching_unchanged():
    student = {"major_current": "Biology", "major_intended": "Computer Science"}
    assert _resolve_major(student) == ("Computer Science", "switching")


def test_real_current_and_same_intended_major_is_staying_unchanged():
    student = {"major_current": "Computer Science", "major_intended": "Computer Science"}
    assert _resolve_major(student) == ("Computer Science", "staying")


def test_real_current_and_na_intended_is_staying_unchanged():
    student = {"major_current": "Computer Science", "major_intended": "N/A"}
    assert _resolve_major(student) == ("Computer Science", "staying")


def test_real_current_and_no_intended_key_is_staying_unchanged():
    student = {"major_current": "Computer Science"}
    assert _resolve_major(student) == ("Computer Science", "staying")


def test_legacy_major_field_used_when_major_current_is_absent_and_intended_present():
    # `major` is the legacy fallback key _resolve_major reads when
    # major_current is missing entirely -- a real value there is a real
    # current major, so a distinct intended major is still a switch.
    student = {"major": "Biology", "major_intended": "Computer Science"}
    assert _resolve_major(student) == ("Computer Science", "switching")
