#!/usr/bin/env python3
"""Check the distributable skill, Markdown/HTML links and original SVG assets."""

from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import hashlib
import json
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/github-homepage-style"
ERRORS = []


def require(condition, message):
    if not condition:
        ERRORS.append(message)


def prose(text):
    return re.sub(r"(?ms)^```[^\n]*\n.*?^```\s*$", "", text)


class HtmlLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag == "img" and values.get("src"):
            self.links.append(values["src"])


def anchor_ids(text):
    parser = HtmlLinks()
    parser.feed(prose(text))
    ids = set(parser.ids)
    for title in re.findall(r"(?m)^#{1,6}\s+(.+)$", prose(text)):
        title = re.sub(r"[^\w\s-]", "", title.lower()).replace(" ", "-")
        ids.add(title)
    return ids


skilltext = (SKILL / "SKILL.md").read_text()
require(skilltext.startswith("---\n"), "Missing skill YAML frontmatter")
front = skilltext.split("---", 2)[1]
require(bool(re.search(r"(?m)^name: github-homepage-style$", front)), "Unexpected skill name")
require(bool(re.search(r"(?m)^description: .+", front)), "Missing skill description")
require("[TODO:" not in skilltext, "Unfinished skill scaffold")
ui = (SKILL / "agents/openai.yaml").read_text()
require("allow_implicit_invocation: true" in ui, "Implicit invocation metadata missing")

record = json.loads((SKILL / "references/保存记录v1.0.json").read_text())
manifest = {item["path"]: item for item in record["files"]}
actual = {p.relative_to(SKILL).as_posix() for p in SKILL.rglob("*") if p.is_file()}
require(set(manifest) == actual - {"references/保存记录v1.0.json"}, "Skill manifest is incomplete")
for relative, item in manifest.items():
    path = SKILL / relative
    if not path.is_file():
        ERRORS.append("Missing manifest file: " + relative)
        continue
    require(path.stat().st_size == item["bytes"], "Size mismatch: " + relative)
    require(hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], "Digest mismatch: " + relative)
snapshot = SKILL / "references/念景首页基准v0.2.1.md"
require(hashlib.sha256(snapshot.read_bytes()).hexdigest() == record["baseline"]["snapshotSha256"], "Baseline digest mismatch")

documents = list(ROOT.rglob("*.md"))
checked = 0
templates = []
for path in documents:
    if ".git" in path.parts:
        continue
    text = path.read_text()
    parser = HtmlLinks()
    parser.feed(prose(text))
    require(len(parser.ids) == len(set(parser.ids)), "Duplicate anchors: " + str(path.relative_to(ROOT)))
    is_template = path.parent == SKILL / "assets"
    if is_template:
        templates.append(parser.ids)
    elif path in {ROOT / "README.md", ROOT / "文档/英文说明v1.0.md"}:
        require("{{" not in text, "Unfilled variable in published document: " + str(path.relative_to(ROOT)))
    links = parser.links + re.findall(r"\]\(([^)\n]+)\)", prose(text))
    for target in links:
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith("//") or "{{" in target:
            continue
        if is_template and parsed.path:
            continue  # Paths in template skeletons belong to the future target repo.
        destination = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
        require(destination.is_relative_to(ROOT), "Link escapes repository: " + target)
        require(destination.exists(), f"Missing link in {path.relative_to(ROOT)}: {target}")
        if parsed.fragment and destination.is_file() and destination.suffix == ".md":
            require(unquote(parsed.fragment) in anchor_ids(destination.read_text()), f"Missing anchor in {path.relative_to(ROOT)}: {target}")
        checked += 1
require(len(templates) == 2 and templates[0] == templates[1], "Template language navigation differs")

fixed = {"README.md", "SKILL.md", "openai.yaml", "LICENSE", ".gitignore"}
files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
for path in files:
    require(not path.is_symlink(), "Unexpected symlink: " + str(path.relative_to(ROOT)))
    if path.name not in fixed:
        require("_" not in path.name and bool(re.search(r"v\d+\.\d+(?:\.\d+)?\.[a-z0-9]+$", path.name)), "Unversioned filename: " + path.name)
    if path.suffix in {".md", ".json", ".yml", ".yaml", ".svg"}:
        text = path.read_text()
        require(not re.search(r"/Users/|/home/[A-Za-z0-9.-]+/|[A-Za-z]:\\Users\\", text), "Local user path in public file: " + str(path.relative_to(ROOT)))
    if path.suffix == ".svg":
        tree = ET.parse(path)
        require(tree.getroot().tag == "{http://www.w3.org/2000/svg}svg", "Invalid SVG root")
        require("<script" not in path.read_text().lower(), "Unexpected script in SVG")

report = {"files": len(files), "skillFiles": len(actual), "localLinks": checked, "bilingualTemplateAnchors": len(templates[0]) if templates else 0, "errors": ERRORS}
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(1 if ERRORS else 0)
