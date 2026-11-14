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
ASS_FONT = re.compile(r"\\fn(?P<font>[^\\]*)", re.IGNORECASE)


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


def _visible_positions(text: str) -> tuple[str, list[tuple[int, int]]]:
    visible = []
    positions = []
    index = 0
    while index < len(text):
        if text[index] == "{":
            close = text.find("}", index + 1)
            if close < 0:
                break
            index = close + 1
        elif text[index:index + 2] in (r"\N", r"\n", r"\h"):
            visible.append(" ")
            positions.append((index, index + 2))
            index += 2
        else:
            visible.append(text[index])
            positions.append((index, index + 1))
            index += 1
    return "".join(visible), positions


def _short_meaning(meaning: str) -> str:
    return re.split(r"[\(（\[［;；]", meaning, maxsplit=1)[0].strip(" ;；,，")


def _font_tag(font_name: str) -> str:
    safe_font = font_name.replace("\\", "").replace("}", "")
    return f"{{\\fn{safe_font}}}" if safe_font else ""


def _font_at(text: str, end: int, default: str) -> str:
    current = default
    for tag in TAG.finditer(text[:end]):
        for command in ASS_FONT.finditer(tag.group()[1:-1]):
            current = command.group("font").strip()
    return current


def _annotation_items(annotation: str) -> list[str]:
    items = []
    start = 0
    depth = 0
    for index, character in enumerate(annotation):
        if character in "(（[［":
            depth += 1
        elif character in ")）]］":
            depth = max(0, depth - 1)
        elif character in ";；" and depth == 0:
            items.append(annotation[start:index].strip())
            start = index + 1
    items.append(annotation[start:].strip())
    return [item for item in items if item]


def _inline_annotations(text: str, annotation: str, chinese_font: str, english_font: str) -> str:
    visible, positions = _visible_positions(text)
    if not visible or not positions:
        return text
    insertions = []
    for item in _annotation_items(annotation):
        span, separator, meaning = item.partition(": ")
        short = _short_meaning(meaning) if separator else ""
        if not span or not short:
            continue
        start = visible.find(span)
        if start < 0:
            continue
        end = start + len(span)
        if end > len(positions):
            continue
        raw_end = positions[end - 1][1]
        current_english_font = _font_at(text, raw_end, english_font)
        chinese_tag = _font_tag(chinese_font) if chinese_font and chinese_font != current_english_font else ""
        english_tag = _font_tag(current_english_font) if chinese_tag else ""
        insertions.append((raw_end, f" ({chinese_tag}{short}{english_tag})"))
    for index, value in sorted(insertions, reverse=True):
        text = text[:index] + value + text[index:]
    return text


def _leading_tags(text: str) -> str:
    match = re.match(r"[ \t]*(?:\{[^{}]*\})*", text)
    return match.group() if match else ""


def _style_size(styles: dict[str, float], name: str) -> float | None:
    return styles.get(name.strip().casefold())


def _effective_style(text: str, event_style: str, styles: dict[str, dict[str, str]]) -> str | None:
    current = event_style.strip().casefold()
    if current not in styles:
        current = None
    for tag in TAG.finditer(_leading_tags(text)):
        for command in ASS_COMMAND.finditer(tag.group()[1:-1]):
            if command.group("size") is None:
                candidate = command.group("style").strip().casefold() or event_style.strip().casefold()
                current = candidate if candidate in styles else None
    return current


def _style_font_name(styles: dict[str, dict[str, str]], name: str | None) -> str:
    return styles.get(name or "", {}).get("fontname", "").strip()


def _effective_font_name(text: str, style: str | None, styles: dict[str, dict[str, str]]) -> str:
    current = _style_font_name(styles, style)
    for tag in TAG.finditer(_leading_tags(text)):
        for command in ASS_FONT.finditer(tag.group()[1:-1]):
            current = command.group("font").strip()
    return current


def _style_display_name(styles: dict[str, dict[str, str]], name: str) -> str:
    return styles[name].get("name", name)


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


def _rewrite_style(
    text: str, target_style: str, font_name: str, styles: dict[str, dict[str, str]]
) -> str:
    """Apply a target ASS style while retaining the segment's original font."""
    prefix = _leading_tags(text)
    leading = prefix.lstrip(" \t")
    whitespace = prefix[:len(prefix) - len(leading)]
    retained = []
    for tag in TAG.finditer(leading):
        content = re.sub(r"\\r[^\\]*", "", tag.group()[1:-1], flags=re.IGNORECASE)
        if content:
            retained.append("{" + content + "}")
    safe_font = font_name.replace("\\", "").replace("}", "")
    reset = f"{{\\r{_style_display_name(styles, target_style)}\\fn{safe_font}}}"
    return whitespace + reset + "".join(retained) + text[len(prefix):]


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
        self._styles: dict[str, dict[str, str]] = {}
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
                        name = style.get("name", "").strip()
                        if name:
                            self._styles[name.casefold()] = {key: value.strip() for key, value in style.items()}
                        try:
                            size = float(style["fontsize"].strip())
                        except (KeyError, ValueError):
                            pass
                        else:
                            if not math.isfinite(size) or size <= 0:
                                continue
                            self._style_sizes[name.casefold()] = size
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
            if not annotation.strip():
                # Keep the source English style; some source Chinese styles use
                # negative margins that hide a line in common media players.
                lines[dialogue.line_index] = line[:dialogue.text_start] + layout.english + line[len(content):]
                continue
            chinese_style = _effective_style(layout.chinese, layout.event_style, self._styles)
            english_style = _effective_style(layout.english, layout.event_style, self._styles)
            chinese_font = _effective_font_name(layout.chinese, chinese_style, self._styles)
            english_font = _effective_font_name(layout.english, english_style, self._styles)
            chinese_size = _effective_font_size(layout.chinese, layout.event_style, self._style_sizes)
            english_size = _effective_font_size(layout.english, layout.event_style, self._style_sizes)
            swap_size = chinese_size is not None and english_size is not None and chinese_size > english_size
            english_source = _inline_annotations(layout.english, annotation, chinese_font, english_font)
            translated = _replace_visible(layout.chinese, annotation)
            swap_style = (
                chinese_style is not None and english_style is not None
                and chinese_style != english_style and chinese_font and english_font
            )
            if swap_style:
                english = _rewrite_style(english_source, chinese_style, english_font, self._styles)
                translated = _rewrite_style(translated, english_style, chinese_font, self._styles)
                english = _with_font_size(english, chinese_size if swap_size else english_size)
                translated = _with_font_size(translated, english_size if swap_size else chinese_size)
            else:
                english = _with_font_size(english_source, chinese_size if swap_size else None)
                if annotation.strip() and TAG.search(layout.english) and not _has_style_reset(layout.chinese):
                    if layout.event_style:
                        # Reset the base style so English-only overrides do not leak into the notes.
                        translated = f"{{\\r{layout.event_style}}}" + translated
                translated = _with_font_size(translated, english_size if swap_size else None)
            replacement = english + layout.separator + translated
            lines[dialogue.line_index] = line[:dialogue.text_start] + replacement + line[len(content):]
        return _encode("".join(lines), self.encoding)
