"""Snapshot web pages as Markdown notes for the bot: fetch (cached in raw/), keep only the page body, convert, make
links absolute, drop link-only sidebars. Use it for public pages (university rules, finance and travel pages) the bot
should quote; re-run it when a page changes, and keep the date in the note's file name.

Usage: python snap.py OUT.md URL [URL ...]      -> one Markdown section per URL (title, "Source: <url>", body)
       python snap.py --links URL                -> list the links found in the page body (to find pages to add)
Needs (a separate venv is fine): pip install requests beautifulsoup4 markdownify html5lib

Site rules: BODY maps a host to CSS selectors of its page body (the first with real text wins; default: main, article,
body). Add your university's hosts there when the default picks up menus. Some university CMS pages nest <div>s inside
<p>, which only the html5lib parser reads correctly, so it is used for every page. FAQ accordions: with
section(url, questions=True) the accordion buttons' text (the questions) is kept as text.
"""
import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment
from markdownify import MarkdownConverter

HERE = Path(__file__).parent
RAW = HERE / "raw"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# page-body container per site, first match with real text wins (examples; add your own hosts)
BODY = {
    "www.example.edu": ["main article", "main", ".layout-content"],
    "www.gsa.gov": ["main", "#main-content"],
}
# never part of the body text
DROP = ["script", "style", "noscript", "iframe", "form", "svg", "img", "picture", "video", "button", "nav",
        ".breadcrumb", ".breadcrumbs", "#breadcrumb", ".element-invisible", ".visually-hidden", ".sr-only",
        ".social-share", ".print-link", ".feedback"]
# FAQ questions are often accordion buttons; with questions=True their text is kept
ACCORDION = "button.accordion-button, button.js-accordion__toggle"
# sidebar sections repeated on many pages; dropped when they are only lists of links
SIDEBARS = {"resources", "related articles", "policies and procedures", "related policies", "related links",
            "related procedures", "forms", "related forms", "quick links", "helpful links", "contact"}


def fetch(url: str) -> tuple[str, str]:
    """(final URL, HTML), from the raw/ cache when this URL was fetched before (delete raw/ to refetch)."""
    RAW.mkdir(exist_ok=True)
    p = RAW / (hashlib.sha1(url.encode()).hexdigest()[:12] + ".html")
    if p.exists():
        head, html = p.read_text(encoding="utf-8").split("\n", 1)
        return head[5:-4], html
    r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    html, final = r.content.decode("utf-8", errors="replace"), r.url
    p.write_text(f"<!-- {final} -->\n" + html, encoding="utf-8")
    return final, html


class MD(MarkdownConverter):
    def convert_a(self, el, text, *args, **kwargs):
        href = el.get("href") or ""
        text = (text or "").strip()
        if not href or href.startswith(("javascript:", "#")) or not text:
            return text
        if href.startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            return text if addr.lower() in text.lower() else f"{text} ({addr})"
        if "safelinks.protection.outlook.com" in href:
            return text
        if text == href:
            return f"<{href}>"
        return f"[{text}]({href})"


def body_of(url: str, html: str, questions: bool = False):
    soup = BeautifulSoup(html, "html5lib")
    title = soup.find("h1")
    title = title.get_text(" ", strip=True) if title else ""
    if not title and soup.title:
        title = soup.title.get_text(strip=True).split(" | ")[0]
    host = urlparse(url).netloc
    node = None
    for sel in BODY.get(host, ["main", "article", "body"]):
        node = soup.select_one(sel)
        if node and len(node.get_text(strip=True)) > 200:
            break
    if node is None:
        node = soup.body
    for c in node.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    if questions:
        for button in node.select(ACCORDION):
            button.unwrap()
    for sel in DROP:
        for el in node.select(sel):
            el.decompose()
    for a in node.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith(("mailto:", "javascript:", "#", "tel:")):
            a["href"] = urljoin(url, href)
    h1 = node.find("h1")  # a page title inside the body would repeat the section heading
    if h1 and h1.get_text(" ", strip=True) == title:
        h1.decompose()
    return title or url, node


def link_only(lines: list[str]) -> bool:
    lines = [l.strip() for l in lines if l.strip()]
    if not lines:
        return True
    linky = [l for l in lines if re.fullmatch(r"(- )?\[[^\]]+\]\([^)]+\)\.?|(- )?<[^>]+>|(- )?[^\[\]()]{0,60} \([^)@ ]+@[^)]+\)", l)]
    return len(linky) >= 0.8 * len(lines)


def drop_sidebars(md: str) -> str:
    parts = re.split(r"(?m)^(?=#{1,6} )", md)
    keep = []
    for part in parts:
        head, _, rest = part.partition("\n")
        name = re.sub(r"[#*]", "", head).strip().lower()
        if name in SIDEBARS and link_only([l for l in rest.splitlines() if l.strip() not in ("---",)]):
            continue
        keep.append(part)
    return "".join(keep)


def to_markdown(node) -> str:
    md = MD(heading_style="ATX", bullets="-", strip=["img"], escape_asterisks=False, escape_underscores=False,
            escape_misc=False, table_infer_header=True).convert_soup(node)
    md = md.replace("\xa0", " ").replace("​", "")
    md = re.sub(r"\*\*\*\*(.+?)\*\*\*\*", r"**\1**", md)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = drop_sidebars(md)
    md = re.sub(r"\n(---\n\s*)+$", "\n", md.strip() + "\n")
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def section(url: str, level: int = 2, questions: bool = False) -> str:
    final, html = fetch(url)
    title, node = body_of(final, html, questions)
    md = to_markdown(node)
    # headings inside the page start one level below the page title
    md = re.sub(r"^(#{1,6}) ", lambda m: "#" * min(max(len(m.group(1)), 2) + level - 1, 6) + " ", md, flags=re.M)
    return f"{'#' * level} {title}\n\nSource: <{final}>\n\n{md}\n"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    if sys.argv[1] == "--links":
        final, html = fetch(sys.argv[2])
        _, node = body_of(final, html)
        seen = set()
        for a in node.find_all("a", href=True):
            h = a["href"].split("#")[0]
            if h.startswith("http") and h not in seen:
                seen.add(h)
                print(f"{a.get_text(' ', strip=True)[:70]:70s} {h}")
    else:
        out = Path(sys.argv[1])
        parts = []
        for u in sys.argv[2:]:
            try:
                parts.append(section(u))
                print(f"ok   {u}  ({len(parts[-1])} chars)")
            except Exception as e:
                print(f"FAIL {u}: {e}")
        out.write_text("\n".join(parts), encoding="utf-8")
        print(f"wrote {out} ({sum(map(len, parts))} chars)")
