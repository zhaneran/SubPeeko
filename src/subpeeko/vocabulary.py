"""Conservative vocabulary hints for the model, not an official syllabus."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files

LEVELS = ("highschool", "cet4", "cet6", "postgrad")
WORDS = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")
IRREGULAR = {
    "am": "be", "are": "be", "is": "be", "was": "be", "were": "be", "been": "be",
    "did": "do", "done": "do", "does": "do", "had": "have", "has": "have",
    "went": "go", "gone": "go", "got": "get", "gotten": "get", "took": "take",
    "taken": "take", "saw": "see", "seen": "see", "said": "say", "made": "make",
    "knew": "know", "known": "know", "thought": "think", "came": "come",
    "gave": "give", "given": "give", "told": "tell", "left": "leave",
}
AMBIGUOUS_WORDS = {
    "back", "bank", "bear", "break", "call", "case", "charge", "come", "court", "cut",
    "deal", "draft", "face", "figure", "fine", "fire", "get", "give", "go", "handle",
    "head", "hold", "issue", "keep", "leave", "light", "look", "make", "matter", "mean",
    "pick", "play", "put", "raise", "right", "rock", "run", "screen", "set", "shoot",
    "sound", "spot", "stand", "strike", "table", "take", "turn", "work",
}


@lru_cache(maxsize=1)
def vocabulary() -> dict[str, int]:
    return json.loads(files("subpeeko").joinpath("data/vocabulary.json").read_text(encoding="utf-8"))


def _base_forms(word: str) -> list[str]:
    # ponytail: lightweight morphology can be ambiguous; model review handles uncertain forms.
    forms = [word]
    if word in IRREGULAR:
        forms.append(IRREGULAR[word])
    if word.endswith("ies") and len(word) > 4:
        forms.append(word[:-3] + "y")
    if word.endswith("ing") and len(word) > 5:
        stem = word[:-3]
        forms.extend((stem, stem + "e", stem[:-1] if len(stem) > 1 and stem[-1] == stem[-2] else stem))
    if word.endswith("ed") and len(word) > 4:
        stem = word[:-2]
        forms.extend((stem, stem + "e", stem[:-1] if len(stem) > 1 and stem[-1] == stem[-2] else stem))
    if word.endswith("es") and len(word) > 4:
        forms.extend((word[:-1], word[:-2]))
    elif word.endswith("s") and len(word) > 3:
        forms.append(word[:-1])
    return forms


def vocabulary_hints(english: str, level: str) -> list[dict[str, str]]:
    known = vocabulary()
    target = LEVELS.index(level)
    hints = []
    seen = set()
    for match in WORDS.finditer(english):
        word = match.group().casefold().replace("\u2019", "'")
        if word in seen:
            continue
        seen.add(word)
        ranks = [known[form] for form in _base_forms(word) if form in known]
        if not ranks:
            hints.append({"word": match.group(), "level": "unknown"})
        elif min(ranks) > target:
            hints.append({"word": match.group(), "level": LEVELS[min(ranks)]})
    return hints


def ambiguous_words(english: str) -> list[str]:
    """Flag familiar words whose contextual meanings may need model review."""
    found = []
    for match in WORDS.finditer(english):
        word = match.group().casefold().replace("\u2019", "'")
        if any(form in AMBIGUOUS_WORDS for form in _base_forms(word)) and match.group() not in found:
            found.append(match.group())
    return found
