"""What counts as the name of a control.

This lived in the sweep, and the drift detector did not know about it. The two
halves of the system then disagreed about what a field is, and the disagreement
turned into a loop the reviewer had to keep closing by hand:

    drift sees "TT" on the screen and proposes adding it
    the reviewer approves, so "TT" is written into the document
    the sweep sees a name no evidence can describe and proposes removing it
    the reviewer approves, so "TT" is removed
    the next crawl sees "TT" on the screen again

Every pass was doing its job. The rule simply had to be in one place, so it is
here, and both sides import it.
"""
from __future__ import annotations

import re

ZERO_WIDTH = "​‌‍﻿⁠"

NUMERIC = re.compile(r"^[\d.,%+\-]+$")
INITIALS = re.compile(r"^[A-Z]{1,3}$")
CLOCK = re.compile(r"^\d{1,2}[:/]\d{2}")
DATEISH = re.compile(r"^\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}$")

# Short all-capital names that are real, so the initials rule cannot eat them.
REAL_ACRONYMS = {"ID", "OS", "URL", "API", "UI", "QPS", "CPM", "SSP", "DSP",
                 "IAB", "GDPR", "CCPA", "COPPA", "AI", "TV", "CTV", "PMP"}


def is_control_name(name: str) -> bool:
    """Could a person point at this and call it by name?"""
    return not is_not_a_control(name)


# A placeholder is instruction text sitting inside an empty field. It is not the
# field's name, it disappears the moment anyone types, and documenting it gives
# entries like "Enter publisher name" where "Publisher Name" belongs.
# Deliberately narrow. "Add condition", "Select all" and "Choose file" are
# button labels: buttons are imperative by nature, and rejecting a real control
# costs a field missing from the document, which is worse than the noise. These
# openers are placeholder language rather than action language.
PLACEHOLDER_OPENERS = (
    "enter ", "type ", "search by ", "start typing", "paste ",
    "e.g.", "eg ", "example:", "your ",
)

# Help text, the sentence a tooltip shows. Whole sentences are never names.
SENTENCE = re.compile(r"[.!?]\s*$")

# A specimen value shown inside an empty field: an address, an example email.
SPECIMEN = re.compile(r"^\S+@\S+\.\S+$|^https?://|^www\.", re.I)


def looks_like_placeholder(name: str) -> bool:
    bare = (name or "").strip()
    low = bare.lower()
    if bare.endswith("...") or bare.endswith("\u2026"):
        return True                       # "Search by name or ID..."
    if SPECIMEN.match(bare):
        return True                       # your@email.com, https://example.com
    return any(low.startswith(o) for o in PLACEHOLDER_OPENERS)


def looks_like_help_text(name: str) -> bool:
    bare = (name or "").strip()
    if len(bare.split()) >= 7:
        return True                       # a sentence, not a label
    return bool(SENTENCE.search(bare)) and len(bare.split()) >= 4


def looks_like_heading(name: str) -> bool:
    """A section heading inside a form, such as PUBLISHER DETAILS."""
    bare = (name or "").strip()
    words = bare.split()
    return (len(words) >= 2 and bare.isupper()
            and all(w.isalpha() or w in {"&", "/"} for w in words))


def is_not_a_control(name: str) -> bool:
    """Names no evidence can turn into a documented field.

    A value the crawler read out of a table cell, an avatar, or a spacer. Kept
    deliberately narrow: the cost of wrongly rejecting a real control is a
    field missing from the document, which is worse than the noise.
    """
    bare = "".join(c for c in (name or "") if c not in ZERO_WIDTH).strip()
    if not bare:
        return True                       # a zero-width spacer read as a field
    if NUMERIC.match(bare):
        return True                       # 0, 0.01, 12.5%
    if CLOCK.match(bare) or DATEISH.match(bare):
        return True                       # a timestamp or date from a cell
    if INITIALS.match(bare) and bare not in REAL_ACRONYMS:
        return True                       # TT, the initials in an avatar
    if looks_like_placeholder(bare):
        return True                       # "Enter publisher name"
    if looks_like_help_text(bare):
        return True                       # a tooltip sentence
    if looks_like_heading(bare):
        return True                       # PUBLISHER DETAILS
    return False


def why_not(name: str) -> str:
    """A sentence a person can read, for when this is reported."""
    bare = "".join(c for c in (name or "") if c not in ZERO_WIDTH).strip()
    if not bare:
        return "an empty or zero-width name, which is a layout spacer"
    if NUMERIC.match(bare):
        return "a bare number, which is a value rather than a control"
    if CLOCK.match(bare) or DATEISH.match(bare):
        return "a date or time, which is a value rather than a control"
    if INITIALS.match(bare) and bare not in REAL_ACRONYMS:
        return "initials, which is what an avatar shows rather than a control"
    if looks_like_placeholder(bare):
        return ("placeholder text, which sits inside an empty field and "
                "disappears the moment anyone types")
    if looks_like_help_text(bare):
        return "help text, which is a sentence about a control rather than its name"
    if looks_like_heading(bare):
        return "a heading that groups fields, rather than a field"
    return ""
