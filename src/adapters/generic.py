"""Generic career-page adapter (source key: ``generic``).

Phase 1 status: HONEST STUB. It performs NO network requests and returns
MANUAL_REVIEW with the company's careers URL (when known) plus a recommended
manual workflow. Real HTML parsing of arbitrary career pages arrives in
Phase 3 - until then this adapter never fabricates results.
"""
from __future__ import annotations

from typing import Union

from ..models import (
    AdapterResult,
    Company,
    ResultStatus,
    SearchMode,
    SearchQuery,
    SourceType,
)
from .base import SourceAdapter, register


@register
class GenericCareersAdapter(SourceAdapter):
    """Fallback adapter for official company career pages."""

    source_key = "generic"
    source_type = SourceType.COMPANY_CAREERS
    search_mode = SearchMode.COMPANY

    def discover(self, company: Company) -> AdapterResult:
        url = company.careers_url
        if not url:
            reason = (
                "No careers URL configured for this company and automatic "
                "career-page discovery is not implemented yet (Phase 2).")
            action = (
                "Add the careers URL to config/companies.csv, or open the "
                "company website and check the careers page manually.")
        else:
            reason = (
                "Automatic parsing of this career page is not implemented "
                "yet (Phase 3); no requests were made.")
            action = (
                f"Open {url} in a browser and review open positions manually "
                "until the parser for this site type is available.")
        return self.manual_review(reason=reason, url=url,
                                  company=company.company_name, action=action)

    def search(self, query: SearchQuery) -> AdapterResult:
        return self.not_available(
            "The generic career-page adapter only works in company mode.")

    def fetch_jobs(self, target: Union[Company, SearchQuery]) -> AdapterResult:
        if isinstance(target, Company):
            return self.discover(target)
        return self.search(target)
