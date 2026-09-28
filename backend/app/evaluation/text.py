"""Basecamp comment HTML -> compact plain text for Claude (STORY-004).

Plain text costs far fewer tokens than HTML. Two things the reviewer relies on
are kept as short inline markers:

- The selected problem, which students highlight in yellow, becomes
  [SELECTED]...[/SELECTED]. Two forms occur in the ST0 history (2026-09-25
  extract, 45 ST0 ##Critique## comments): an inline style
  background-color: rgb(250, 247, 133) (12 comments), and Basecamp's newer
  <mark style="background-color: var(--highlight-bg-1)"> (8 comments), used
  the same way. Other highlight colours (one comment each) mark every
  problem, not a selection, and are ignored.
- Embedded files (<bc-attachment>) become [image: name] / [file: name] where
  they sit, so Claude can see e.g. that a screenshot follows the dataset
  section. @mentions use the same tag and are dropped.
"""
import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple

_SELECTED_STYLE = re.compile(
    r"background-color\s*:\s*(rgb\(\s*250\s*,\s*247\s*,\s*133\s*\)|var\(\s*--highlight-bg-1\s*\)|#faf785)",
    re.IGNORECASE,
)
_BLOCK = {"div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "pre", "figure"}
_VOID = {"br", "hr", "img", "input", "meta", "link", "wbr"}
_MENTION = "application/vnd.basecamp.mention"
_MARKER = re.compile(r"\[/?SELECTED\]|\[(?:file|image): [^\]]*\]")


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.stack: List[Tuple[str, bool]] = []  # (tag, opened a [SELECTED])
        self.selected_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = dict(attrs)
        if tag == "bc-attachment":
            self._attachment(values)
        if tag in ("br", "hr"):
            self.out.append("\n")
        if tag in _BLOCK:
            self.out.append("\n- " if tag == "li" else "\n")
        if tag in _VOID:
            return
        opens = bool(_SELECTED_STYLE.search(values.get("style") or "")) and self.selected_depth == 0
        if opens:
            self.out.append("[SELECTED]")
        if opens or self.selected_depth:
            self.selected_depth += 1
        self.stack.append((tag, opens))

    def handle_endtag(self, tag: str) -> None:
        if not any(open_tag == tag for open_tag, _ in self.stack):
            return  # stray end tag
        while self.stack:
            open_tag, _ = self.stack[-1]
            self._pop()
            if open_tag == tag:
                break
        if tag in _BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        self.out.append(re.sub(r"\s+", " ", data))

    def close(self) -> None:
        super().close()
        while self.stack:
            self._pop()

    def _pop(self) -> None:
        _, opened = self.stack.pop()
        if self.selected_depth:
            self.selected_depth -= 1
        if opened:
            self.out.append("[/SELECTED]")

    def _attachment(self, values: dict) -> None:
        content_type = (values.get("content-type") or "").lower()
        if content_type == _MENTION:
            return
        name = values.get("filename") or "unnamed"
        kind = "image" if content_type.startswith("image/") else "file"
        self.out.append(f" [{kind}: {name}] ")


def html_to_text(html: str) -> str:
    converter = _Converter()
    converter.feed(html)
    converter.close()
    text = "".join(converter.out)
    # One highlight often spans several paragraphs or list items: merge
    # adjacent [SELECTED] runs into one block.
    text = re.sub(r"\[/SELECTED\](\s*(?:- )?)\[SELECTED\]", r"\1", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line != "-"]
    following = [""] * len(lines)  # the next non-empty line after each index
    for index in range(len(lines) - 2, -1, -1):
        following[index] = lines[index + 1] or following[index + 1]
    kept: List[str] = []
    previous = ""  # the last non-empty line kept
    for index, line in enumerate(lines):
        if not line and previous.startswith("- ") and following[index].startswith("- "):
            continue  # no blank line between two items of one list
        kept.append(line)
        previous = line or previous
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def without_markers(text: str) -> str:
    """The student's own words only: markers removed."""
    return _MARKER.sub("", text).strip()
