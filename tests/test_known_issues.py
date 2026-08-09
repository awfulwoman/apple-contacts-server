"""Tests for defects found in review that are NOT yet fixed.

Empty right now — every defect found in the code-quality review has a fix and
a passing test elsewhere in this suite. Kept as a placeholder: when the next
review finds something real but not yet worth fixing immediately, put its
test here, marked `known_issues`, so the gap is executable rather than prose
in a report. Don't `xfail` them — an unfixed regression should stay visible
as a failure, not get silently swallowed.
"""
from __future__ import annotations
import pytest

pytestmark = pytest.mark.known_issues
