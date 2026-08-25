"""F2Media resolver package.

Public entry point: :class:`F2MediaResolver` (see ``f2medi_resolver``).
"""

from resolvers.f2medi_resolver import F2MediaResolver
from resolvers.models import (
    CandidateScore,
    F2MediaPage,
    ParsedStream,
    ResolverResult,
    SearchCandidate,
)

__all__ = [
    "F2MediaResolver",
    "CandidateScore",
    "F2MediaPage",
    "ParsedStream",
    "ResolverResult",
    "SearchCandidate",
]
