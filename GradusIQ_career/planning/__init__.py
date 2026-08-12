"""Term-organized academic planning: term dates, planned courses, course search.

Phase 1 of the term-organized Academic Record. Everything here is ADDITIVE to
the transcript pipeline and reads nothing it owns except academic_terms:

  * no module in this package imports from GradusIQ_career.academics
  * no module writes course_records
  * gpa.py does not read planned_courses, and nothing here changes what it does

The one shared dependency is transcript.terms -- SEASON_ORDER and
parse_term_label -- which is the point rather than a coupling to be avoided: a
term's identity must mean the same thing whether it arrived from a transcript
or from a registrar's calendar, or the two would file the same semester under
different keys.
"""
