"""Student-scoped deterministic course status, eligibility, and discovery."""

from .catalog import LocalCatalogRepository
from .models import (
    CareerSkillNeed,
    CatalogInstitution,
    CourseCandidate,
    CourseDiscoveryContext,
    CourseEligibilityResult,
    CourseEligibilityStatus,
    CourseSearchQuery,
    EvidenceState,
    FinalCourseVerification,
    PrerequisiteStatus,
    StudentCourseState,
    StudentCourseStatus,
    VerificationDisposition,
    canonical_course_code,
)
from .prerequisites import evaluate_prerequisites


class CourseDiscoveryService:
    def __init__(self, context: CourseDiscoveryContext, catalog: LocalCatalogRepository | None = None):
        self.context = context
        self.catalog = catalog or LocalCatalogRepository()

    def student_course_status(self, course_code: str) -> StudentCourseStatus:
        normalized = canonical_course_code(course_code)
        if normalized is None:
            return StudentCourseStatus(
                institution=self.context.institution,
                course_code=course_code,
                state=StudentCourseState.UNKNOWN,
                reason="course code is not a valid institutional identifier",
            )
        if self.catalog.get(self.context.institution, normalized) is None:
            return StudentCourseStatus(
                institution=self.context.institution,
                course_code=normalized,
                state=StudentCourseState.UNKNOWN,
                reason="course code is not present in the institution-scoped catalog",
            )
        home_id = self.context.profile.institution.id
        records = [
            course for course in self.context.profile.academics.courses
            if canonical_course_code(course.course_code) == normalized
            and home_id is not None and course.institution_id == home_id
        ]
        exclusions = {
            exclusion.excluded_course_id
            for exclusion in self.context.profile.academics.repeat_exclusions
        }
        completed = [course for course in records if course.status.lower() == "completed"]
        in_progress = [course for course in records if course.status.lower() == "in_progress"]
        planned = [
            course for course in self.context.planned_courses
            if course.institution == self.context.institution
            and canonical_course_code(course.course_code) == normalized
        ]
        if completed:
            return StudentCourseStatus(
                institution=self.context.institution, course_code=normalized,
                state=StudentCourseState.COMPLETED,
                matching_record_ids=[course.id for course in completed],
                repeat_excluded_record_ids=[course.id for course in completed if course.id in exclusions],
                reason="confirmed academic history contains a completed attempt; repeat exclusions affect GPA, not course-history existence",
            )
        if in_progress:
            return StudentCourseStatus(
                institution=self.context.institution, course_code=normalized,
                state=StudentCourseState.IN_PROGRESS,
                matching_record_ids=[course.id for course in in_progress],
                reason="confirmed academic history contains an in-progress attempt",
            )
        if planned:
            return StudentCourseStatus(
                institution=self.context.institution, course_code=normalized,
                state=StudentCourseState.PLANNED,
                matching_record_ids=[course.id for course in planned],
                reason="trusted student-scoped planning context contains this course",
            )
        return StudentCourseStatus(
            institution=self.context.institution, course_code=normalized,
            state=StudentCourseState.NOT_TAKEN,
            reason="course is absent from confirmed academic history and current plans",
        )

    def check_eligibility(self, course_code: str) -> CourseEligibilityResult:
        existence = self.catalog.verify_course_exists(self.context.institution, course_code)
        student_status = self.student_course_status(course_code)
        normalized = existence.normalized_code or course_code
        if existence.course is None:
            other_institutions = [
                institution for institution in self.catalog.institutions_with_code(course_code)
                if institution != self.context.institution
            ]
            wrong_institution = bool(other_institutions)
            return CourseEligibilityResult(
                institution=self.context.institution, course_code=normalized,
                status=(CourseEligibilityStatus.WRONG_INSTITUTION if wrong_institution
                        else CourseEligibilityStatus.COURSE_NOT_FOUND),
                exists=False, student_status=student_status,
                reasons=[
                    "course exists only outside the trusted home institution"
                    if wrong_institution else
                    "no course exists under this code in the institution-scoped catalog"
                ],
            )
        state_to_status = {
            StudentCourseState.COMPLETED: CourseEligibilityStatus.ALREADY_COMPLETED,
            StudentCourseState.IN_PROGRESS: CourseEligibilityStatus.IN_PROGRESS,
            StudentCourseState.PLANNED: CourseEligibilityStatus.ALREADY_PLANNED,
        }
        if student_status.state in state_to_status:
            return CourseEligibilityResult(
                institution=self.context.institution, course_code=existence.course.course_code,
                status=state_to_status[student_status.state], exists=True,
                student_status=student_status,
                reasons=[student_status.reason], provenance=existence.provenance,
            )
        prerequisite = evaluate_prerequisites(existence.course, self.student_course_status)
        status = {
            PrerequisiteStatus.ELIGIBLE: CourseEligibilityStatus.ELIGIBLE,
            PrerequisiteStatus.INELIGIBLE: CourseEligibilityStatus.INELIGIBLE,
            PrerequisiteStatus.UNRESOLVED: CourseEligibilityStatus.UNRESOLVED,
        }[prerequisite.status]
        return CourseEligibilityResult(
            institution=self.context.institution, course_code=existence.course.course_code,
            status=status, exists=True, student_status=student_status,
            prerequisite_evaluation=prerequisite,
            reasons=prerequisite.reasons, provenance=existence.provenance,
        )

    def discover_candidates(self, need: CareerSkillNeed, limit: int = 10) -> list[CourseCandidate]:
        if need.evidence_state not in {
            EvidenceState.VERIFIED_LOCAL, EvidenceState.EXTERNAL_EVIDENCE_PRESENT
        }:
            return []
        results = self.catalog.search(CourseSearchQuery(
            institution=self.context.institution, query=need.skill, limit=limit
        ))
        return [CourseCandidate(
            need=need,
            search_result=result,
            student_status=self.student_course_status(result.course.course_code),
            eligibility=self.check_eligibility(result.course.course_code),
        ) for result in results]

    def verify_final_recommendation(self, course_code: str) -> FinalCourseVerification:
        eligibility = self.check_eligibility(course_code)
        if eligibility.status == CourseEligibilityStatus.ELIGIBLE and eligibility.provenance:
            disposition = VerificationDisposition.ACCEPT
        elif eligibility.status == CourseEligibilityStatus.UNRESOLVED:
            disposition = VerificationDisposition.FLAG
        else:
            disposition = VerificationDisposition.REJECT
        return FinalCourseVerification(
            disposition=disposition,
            eligibility=eligibility,
            reasons=eligibility.reasons,
        )
