"""Narrow read-only tools for a future C2 agent."""

import time

from .catalog import LocalCatalogRepository
from .models import (
    CourseCodeInput,
    CourseSearchQuery,
    SearchCoursesInput,
    ToolOperationMetadata,
    ToolResult,
)
from .service import CourseDiscoveryService


class ReadOnlyCourseTools:
    """Bound to one trusted context; no method accepts ``student_id``."""

    def __init__(self, service: CourseDiscoveryService, *, monotonic=time.monotonic):
        self.service = service
        self.catalog: LocalCatalogRepository = service.catalog
        self.monotonic = monotonic

    def _metadata(self, name: str, started: float, count: int, status: str) -> ToolOperationMetadata:
        return ToolOperationMetadata(
            tool_name=name,
            duration_ms=max(0, round((self.monotonic() - started) * 1000)),
            result_count=count,
            status=status,
        )

    def search_courses(self, value: SearchCoursesInput) -> ToolResult:
        started = self.monotonic()
        results = self.catalog.search(CourseSearchQuery(
            institution=self.service.context.institution,
            query=value.query,
            limit=value.limit,
        ))
        return ToolResult(
            metadata=self._metadata("search_courses", started, len(results), "success"),
            results=results,
        )

    def get_course(self, value: CourseCodeInput) -> ToolResult:
        started = self.monotonic()
        course = self.catalog.get(self.service.context.institution, value.course_code)
        return ToolResult(
            metadata=self._metadata(
                "get_course", started, int(course is not None),
                "success" if course else "not_found",
            ),
            course=course,
        )

    def get_student_course_status(self, value: CourseCodeInput) -> ToolResult:
        started = self.monotonic()
        status = self.service.student_course_status(value.course_code)
        return ToolResult(
            metadata=self._metadata("get_student_course_status", started, 1, "success"),
            student_status=status,
        )

    def check_course_eligibility(self, value: CourseCodeInput) -> ToolResult:
        started = self.monotonic()
        eligibility = self.service.check_eligibility(value.course_code)
        return ToolResult(
            metadata=self._metadata("check_course_eligibility", started, 1, "success"),
            eligibility=eligibility,
        )
