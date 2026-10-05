"""Markdown frontmatter: read, and rewrite only the tool's own keys (plan 4.9).

The LLM's keys and the body are kept byte for byte: the tool replaces the YAML block
only when a machine key changes, and re-emits the other keys from their original lines.
"""

import re
from dataclasses import dataclass

import yaml

FENCE = re.compile(r"\A---\n(?:(.*?)\n)?---\n", re.S)     # also an empty `---\n---\n`
TOP_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):")


class Loader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    """Keep YAML 1.2 words such as the decision key `on` as strings."""


Loader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in values if tag != "tag:yaml.org,2002:bool"]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
Loader.add_implicit_resolver("tag:yaml.org,2002:bool",
                             re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$"), list("tTfF"))


@dataclass
class Page:
    meta: dict
    raw_meta: str      # the YAML text between the fences ("" when there is none)
    body: str
    has_fm: bool


def split(text: str) -> Page:
    match = FENCE.match(text)
    if not match:
        return Page({}, "", text, False)
    raw = match.group(1) or ""
    meta = yaml.load(raw, Loader=Loader) or {}
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a mapping")
    return Page(meta, raw, text[match.end():], True)


def blocks(raw: str) -> list[tuple[str, str]]:
    """The YAML text cut into (key, lines) blocks of top-level keys, in order."""
    out: list[tuple[str, str]] = []
    for line in raw.split("\n"):
        m = TOP_KEY.match(line)
        if m:
            out.append((m.group(1), line))
        elif out:
            out[-1] = (out[-1][0], out[-1][1] + "\n" + line)
        else:
            out.append(("", line))
    return out


def _flow(value) -> str:
    text = yaml.safe_dump(value, allow_unicode=True, sort_keys=False, default_flow_style=True,
                          width=1000)
    return text.removesuffix("\n...\n").strip()


def dump_value(key: str, value) -> str:
    """`key: value` in the wiki's style: mappings inline, lists one inline item per line."""
    if isinstance(value, list) and value:
        return f"{key}:\n" + "\n".join(f"  - {_flow(item)}" for item in value)
    if isinstance(value, dict) and any(isinstance(v, (dict, list)) for v in value.values()):
        nested = yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=1000)
        return f"{key}:\n" + "\n".join("  " + ln for ln in nested.rstrip("\n").split("\n"))
    return f"{key}: {_flow(value)}"


def set_keys(text: str | Page, values: dict, remove: tuple[str, ...] = ()) -> str:
    """Set (or add at the end) the given top-level keys; other blocks stay byte-identical."""
    page = split(text) if isinstance(text, str) else text
    kept = []
    seen = set()
    for key, chunk in blocks(page.raw_meta) if page.has_fm else []:
        if key in remove:
            continue
        if key in values:
            kept.append(dump_value(key, values[key]))
            seen.add(key)
        else:
            kept.append(chunk)
    kept += [dump_value(k, v) for k, v in values.items() if k not in seen]
    raw = "\n".join(kept)
    return f"---\n{raw}\n---\n" + page.body


def strip_keys(text: str, keys: tuple[str, ...]) -> str:
    """The text without the given top-level keys (used by the path guard)."""
    page = split(text)
    if not page.has_fm:
        return text
    kept = [chunk for key, chunk in blocks(page.raw_meta) if key not in keys]
    return "---\n" + "\n".join(kept) + "\n---\n" + page.body
