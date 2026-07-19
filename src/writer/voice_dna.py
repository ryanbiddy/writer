"""Writer-owned Voice DNA prompt and banned-pattern scanner."""

from __future__ import annotations

import logging
import re
from importlib.resources import files
from typing import Any

log = logging.getLogger("writer.voice_dna")


def _load_voice_dna_prompt() -> str:
    resource = files("writer").joinpath(
        "_data", "voice_dna", "VOICE-DNA.md")
    try:
        return resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        log.warning("Voice DNA prompt could not be loaded: %s", exc)
        return ""


VOICE_DNA_PROMPT = _load_voice_dna_prompt()

_DEAD_AI_LANGUAGE = [
    (r"\bin today'?s\b", "in today's", "Dead AI Language"),
    (
        r"\bit'?s important to note that\b",
        "it's important to note that",
        "Dead AI Language",
    ),
    (
        r"\bit'?s worth noting\b",
        "it's worth noting",
        "Dead AI Language",
    ),
    (r"\bdelv(?:e|ing|es|ed)\b", "delve", "Dead AI Language"),
    (r"\bdive into\b", "dive into", "Dead AI Language"),
    (r"\bunpack\b", "unpack", "Dead AI Language"),
    (r"\bharness\b", "harness", "Dead AI Language"),
    (
        r"\bleverag(?:e|ing|es|ed)\b",
        "leverage",
        "Dead AI Language",
    ),
    (
        r"\butili(?:z|s)(?:e|ing|es|ed)\b",
        "utilize",
        "Dead AI Language",
    ),
    (r"\blandscape\b", "landscape", "Dead AI Language"),
    (r"\brealm\b", "realm", "Dead AI Language"),
    (r"\brobust\b", "robust", "Dead AI Language"),
    (
        r"\bgame[- ]?changer\b",
        "game-changer",
        "Dead AI Language",
    ),
    (
        r"\bcutting[- ]?edge\b",
        "cutting-edge",
        "Dead AI Language",
    ),
    (r"\bstraightforward\b", "straightforward", "Dead AI Language"),
    (
        r"\bi'?d be happy to help\b",
        "i'd be happy to help",
        "Dead AI Language",
    ),
    (r"\bin order to\b", "in order to", "Dead AI Language"),
]

_DEAD_TRANSITIONS = [
    (r"\bfurthermore\b", "furthermore", "Dead Transitions"),
    (r"\badditionally\b", "additionally", "Dead Transitions"),
    (r"\bmoreover\b", "moreover", "Dead Transitions"),
    (r"\bmoving forward\b", "moving forward", "Dead Transitions"),
    (
        r"\bat the end of the day\b",
        "at the end of the day",
        "Dead Transitions",
    ),
    (
        r"\bto put this in perspective\b",
        "to put this in perspective",
        "Dead Transitions",
    ),
    (
        r"\bwhat makes this particularly interesting is\b",
        "what makes this particularly interesting is",
        "Dead Transitions",
    ),
    (
        r"\bthe implications here are\b",
        "the implications here are",
        "Dead Transitions",
    ),
    (r"\bin other words\b", "in other words", "Dead Transitions"),
    (
        r"\bit goes without saying\b",
        "it goes without saying",
        "Dead Transitions",
    ),
]

_ENGAGEMENT_BAIT = [
    (r"\blet that sink in\b", "let that sink in", "Engagement Bait"),
    (r"\bread that again\b", "read that again", "Engagement Bait"),
    (r"\bfull stop\b", "full stop", "Engagement Bait"),
    (
        r"\bthis changes everything\b",
        "this changes everything",
        "Engagement Bait",
    ),
    (
        r"\bare you paying attention\b",
        "are you paying attention",
        "Engagement Bait",
    ),
    (
        r"\byou'?re not ready for this\b",
        "you're not ready for this",
        "Engagement Bait",
    ),
]

_AI_CRINGE = [
    (r"\bsupercharg(?:e|ing|es|ed)\b", "supercharge", "AI Cringe"),
    (r"\bunlock\b", "unlock", "AI Cringe"),
    (r"\bfuture[- ]?proof\b", "future-proof", "AI Cringe"),
    (
        r"\b10[- ]?x your productivity\b",
        "10x your productivity",
        "AI Cringe",
    ),
    (r"\bthe ai revolution\b", "the ai revolution", "AI Cringe"),
    (r"\bin the age of ai\b", "in the age of ai", "AI Cringe"),
]

_GENERIC_INSIDER = [
    (
        r"here'?s the part nobody'?s talking about",
        "here's the part nobody's talking about",
        "Generic Insider Claims",
    ),
    (
        r"\bwhat nobody tells you\b",
        "what nobody tells you",
        "Generic Insider Claims",
    ),
    (
        r"\bmost people don'?t realize\b",
        "most people don't realize",
        "Generic Insider Claims",
    ),
]

_THE_BIG_ONE = [
    (
        r"\b(?:this|it|that|we)'?(?:s|re)?\s+"
        r"(?:isn'?t|is not|aren'?t|are not|wasn'?t|was not)\s+"
        r"[^.!?]{3,80}[.!?]\s+"
        r"(?:this|it|that|we|here)'?(?:s|re)?\s+"
        r"(?:is|are|was)\b",
        "this isn't X. this is Y.",
        "The Big One",
    ),
    (
        r"\bforget\s+[^.!?]{3,80}[.!?]\s+"
        r"(?:this|it|that|here)'?(?:s|re)?\s+(?:is|are)\b",
        "forget X. this is Y.",
        "The Big One",
    ),
    (
        r"^[^a-z]*not\s+[^.!?]{3,80}[.!?]\s+",
        "Not X. Y.",
        "The Big One",
    ),
    (
        r"\bless\s+[^.,!?]{2,40}[,.]\s*more\s+",
        "less X, more Y.",
        "The Big One",
    ),
]

_BANNED_PHRASES: list[tuple[str, str, str]] = (
    _DEAD_AI_LANGUAGE
    + _DEAD_TRANSITIONS
    + _ENGAGEMENT_BAIT
    + _AI_CRINGE
    + _GENERIC_INSIDER
    + _THE_BIG_ONE
)

_COMPILED_BANNED = [
    (re.compile(pattern, re.IGNORECASE | re.MULTILINE), label, category)
    for pattern, label, category in _BANNED_PHRASES
]


def scan(text: str) -> list[dict[str, Any]]:
    """Return structured findings with offsets into the original text."""
    if not text:
        return []
    findings: list[dict[str, Any]] = []
    for pattern, label, category in _COMPILED_BANNED:
        for match in pattern.finditer(text):
            findings.append({
                "phrase": label,
                "position": [match.start(), match.end()],
                "category": category,
                "matched_text": text[match.start():match.end()],
            })
    return findings


def warning_copy() -> str:
    return (
        "Heads up, Writer spotted patterns that can read like AI copy. "
        "Keep the draft, revise it, or turn Voice DNA warnings off."
    )


def prepend_system_prompt(user_system_prompt: str) -> str:
    if not VOICE_DNA_PROMPT:
        return user_system_prompt
    return (
        VOICE_DNA_PROMPT.rstrip()
        + "\n\n---\n\n"
        + (user_system_prompt or "").lstrip()
    )


__all__ = [
    "VOICE_DNA_PROMPT",
    "scan",
    "warning_copy",
    "prepend_system_prompt",
]
