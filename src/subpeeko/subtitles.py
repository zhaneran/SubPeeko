"""Read and modify ASS dialogue without rewriting unrelated source lines."""

from __future__ import annotations

import codecs
import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

TAG = re.compile(r"\{[^{}]*\}")
CHINESE = re.compile(r"[\u3400-\u9fff]")
ENGLISH = re.compile(r"[A-Za-z]{2}")
STYLE_SECTIONS = {"[v4 styles]", "[v4+ styles]", "[v4++ styles]"}
ASS_COMMAND = re.compile(r"\\r(?P<style>[^\\]*)|\\fs(?P<size>-?\d+(?:\.\d+)?)", re.IGNORECASE)


class SubtitleError(Exception):
    pass


@dataclass(frozen=True)
class Dialogue:
    id: int
    line_index: int
    text_start: int
    chinese_start: int
    chinese_end: int
    english: str
    chinese: str
    start: float


@dataclass(frozen=True)
class _DialogueLayout:
    english: str
    chinese: str
    separator: str
    event_style: str


def plain(text: str) -> str:
    return TAG.sub("", text).replace(r"\h", " ").strip()


def _segments(text: str) -> list[tuple[int, int]]:
    result = []
    start = 0
    i = 0
    while i < len(text):
        if text[i] == "{":
            close = text.find("}", i + 1)
            if close < 0:
                return []
            i = close + 1
        elif text[i:i + 2] in (r"\N", r"\n"):
            result.append((start, i))
            i += 2
            start = i
        else:
            i += 1
    result.append((start, len(text)))
    return result


def _time(value: str) -> float:
    try:
        hours, minutes, seconds = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return 0.0


def _decode(data: bytes) -> tuple[str, str]:
    try:
        if data.startswith(codecs.BOM_UTF8):
            return data.decode("utf-8-sig"), "utf-8-sig"
        if data.startswith(codecs.BOM_UTF16_LE):
            return data[len(codecs.BOM_UTF16_LE):].decode("utf-16-le"), "utf-16-le-bom"
        if data.startswith(codecs.BOM_UTF16_BE):
            return data[len(codecs.BOM_UTF16_BE):].decode("utf-16-be"), "utf-16-be-bom"
    except UnicodeDecodeError as exc:
        raise SubtitleError("Invalid subtitle encoding") from exc
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        try:
            return data.decode("gb18030"), "gb18030"
        except UnicodeDecodeError as exc:
            raise SubtitleError("Unsupported subtitle encoding") from exc


def _encode(text: str, encoding: str) -> bytes:
    try:
        if encoding == "utf-16-le-bom":
            return codecs.BOM_UTF16_LE + text.encode("utf-16-le")
        if encoding == "utf-16-be-bom":
            return codecs.BOM_UTF16_BE + text.encode("utf-16-be")
        return text.encode(encoding)
    except UnicodeEncodeError as exc:
        raise SubtitleError("The generated annotations cannot be represented in the input encoding") from exc


def _replace_visible(segment: str, annotation: str) -> str:
    """Retain original override blocks while replacing the visible Chinese text."""
    result = []
    index = 0
    inserted = False
    for match in TAG.finditer(segment):
        if match.start() > index and not inserted:
            result.append(annotation)
            inserted = True
        result.append(match.group())
        index = match.end()
    if index < len(segment) and not inserted:
        result.append(annotation)
        inserted = True
    if not inserted:
        result.append(annotation)
    return "".join(result)


def _leading_tags(text: str) -> str:
    match = re.match(r"[ \t]*(?:\{[^{}]*\})*", text)
    return match.group() if match else ""


def _style_size(styles: dict[str, float], name: str) -> float | None:
    return styles.get(name.strip().casefold())


def _effective_font_size(text: str, event_style: str, styles: dict[str, float]) -> float | None:
    """Return the size at the first visible character in an ASS text group."""
    current = _style_size(styles, event_style)
    for tag in TAG.finditer(_leading_tags(text)):
        for command in ASS_COMMAND.finditer(tag.group()[1:-1]):
            if command.group("size") is not None:
                current = float(command.group("size"))
            else:
                style = command.group("style").strip()
                current = _style_size(styles, style) if style else _style_size(styles, event_style)
    return current


def _format_font_size(size: float) -> str:
    return str(int(size)) if size.is_integer() else format(size, "g")


def _with_font_size(text: str, size: float | None) -> str:
    if size is None or not plain(text):
        return text
    prefix = _leading_tags(text)
    return f"{prefix}{{\\fs{_format_font_size(size)}}}{text[len(prefix):]}"


def _has_style_reset(text: str) -> bool:
    return any(
        command.group("style") is not None
        for tag in TAG.finditer(_leading_tags(text))
        for command in ASS_COMMAND.finditer(tag.group()[1:-1])
        if command.group("size") is None
    )


class AssFile:
    def __init__(self, data: bytes):
        self.source_hash = hashlib.sha256(data).digest()
        text, self.encoding = _decode(data)
        self.lines = text.splitlines(keepends=True)
        self.dialogues: list[Dialogue] = []
        self._layouts: dict[int, _DialogueLayout] = {}
        self._style_sizes: dict[str, float] = {}
        section = ""
        fields: list[str] = []
        style_fields: list[str] = []
        dialogue_id = 0
        saw_events = False
        for line_index, line in enumerate(self.lines):
            content = line.rstrip("\r\n")
            stripped = content.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped.casefold()
                saw_events |= section == "[events]"
                if section not in STYLE_SECTIONS:
                    style_fields = []
                continue
            if section in STYLE_SECTIONS:
                if stripped.casefold().startswith("format:"):
                    style_fields = [item.strip().casefold() for item in stripped.split(":", 1)[1].split(",")]
                    continue
                match = re.match(r"^\s*Style\s*:\s*", content, re.IGNORECASE)
                if match and style_fields and "name" in style_fields and "fontsize" in style_fields:
                    values = content[match.end():].split(",", len(style_fields) - 1)
                    if len(values) == len(style_fields):
                        style = dict(zip(style_fields, values))
                        try:
                            size = float(style["fontsize"].strip())
                        except (KeyError, ValueError):
                            pass
                        else:
                            if not math.isfinite(size) or size <= 0:
                                continue
                            self._style_sizes[style["name"].strip().casefold()] = size
                continue
            if section != "[events]":
                continue
            if stripped.casefold().startswith("format:"):
                fields = [item.strip().casefold() for item in stripped.split(":", 1)[1].split(",")]
                continue
            match = re.match(r"^\s*Dialogue\s*:\s*", content, re.IGNORECASE)
            if not match:
                continue
            dialogue_id += 1
            if not fields or fields[-1] != "text":
                raise SubtitleError("Unsupported ASS event format: Text must be the last field")
            values = content[match.end():].split(",", len(fields) - 1)
            if len(values) != len(fields):
                raise SubtitleError(f"Malformed ASS dialogue on line {line_index + 1}")
            event = dict(zip(fields, values))
            style = event.get("style", "").strip().casefold()
            if "note" in style or any(x in style for x in ("注解", "注释", "译注")):
                continue
            text_start = len(content) - len(values[-1])
            spans = _segments(values[-1])
            if len(spans) < 2:
                continue
            texts = [plain(values[-1][start:end]) for start, end in spans]
            languages = ["zh" if CHINESE.search(item) else "en" if ENGLISH.search(item) else "" for item in texts]
            if "" in languages or set(languages) != {"zh", "en"}:
                continue
            if sum(languages[i] != languages[i - 1] for i in range(1, len(languages))) != 1:
                continue
            chinese_indices = [i for i, language in enumerate(languages) if language == "zh"]
            english_indices = [i for i, language in enumerate(languages) if language == "en"]
            first_transition = min(chinese_indices[0], english_indices[0])
            second_transition = max(chinese_indices[0], english_indices[0])
            first_group = (languages[first_transition], spans[first_transition][0], spans[second_transition - 1][1])
            second_group = (languages[second_transition], spans[second_transition][0], spans[-1][1])
            first_separator = values[-1][spans[second_transition - 1][1]:spans[second_transition][0]]
            groups = {first_group[0]: values[-1][first_group[1]:first_group[2]],
                      second_group[0]: values[-1][second_group[1]:second_group[2]]}
            self.dialogues.append(Dialogue(
                id=dialogue_id, line_index=line_index, text_start=text_start,
                chinese_start=spans[chinese_indices[0]][0], chinese_end=spans[chinese_indices[-1]][1],
                english=" ".join(texts[i] for i in english_indices),
                chinese=" ".join(texts[i] for i in chinese_indices), start=_time(event.get("start", "")),
            ))
            self._layouts[dialogue_id] = _DialogueLayout(
                english=groups["en"], chinese=groups["zh"], separator=first_separator,
                event_style=event.get("style", "").strip(),
            )
        if not saw_events:
            raise SubtitleError("The file does not contain an ASS [Events] section")
        self.dialogues.sort(key=lambda item: (item.start, item.line_index))

    @classmethod
    def read(cls, path: Path) -> "AssFile":
        try:
            return cls(path.read_bytes())
        except OSError as exc:
            raise SubtitleError(f"Cannot read subtitle: {path}") from exc

    def render(self, annotations: dict[int, str]) -> bytes:
        lines = self.lines.copy()
        for dialogue in self.dialogues:
            if dialogue.id not in annotations:
                raise SubtitleError(f"Missing result for dialogue {dialogue.id}")
            line = lines[dialogue.line_index]
            content = line.rstrip("\r\n")
            layout = self._layouts[dialogue.id]
            annotation = annotations[dialogue.id]
            chinese_size = _effective_font_size(layout.chinese, layout.event_style, self._style_sizes)
            english_size = _effective_font_size(layout.english, layout.event_style, self._style_sizes)
            swap_size = chinese_size is not None and english_size is not None and chinese_size > english_size
            english = _with_font_size(layout.english, chinese_size if swap_size else None)
            translated = _replace_visible(layout.chinese, annotation)
            if annotation.strip() and TAG.search(layout.english) and not _has_style_reset(layout.chinese):
                if layout.event_style:
                    # Reset the base style so English-only overrides do not leak into the notes.
                    translated = f"{{\\r{layout.event_style}}}" + translated
            translated = _with_font_size(translated, english_size if swap_size else None)
            replacement = english + layout.separator + translated
            lines[dialogue.line_index] = line[:dialogue.text_start] + replacement + line[len(content):]
        return _encode("".join(lines), self.encoding)
