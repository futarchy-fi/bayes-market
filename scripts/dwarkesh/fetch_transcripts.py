#!/usr/bin/env python3
"""Fetch Dwarkesh Podcast Substack text transcripts (TEXT ONLY — zero audio/video).

Queries https://www.dwarkesh.com/api/v1/posts and /api/v1/posts/{slug}, strips
HTML markup to clean plain text, and caches JSON/TXT files in a local scratch
directory (never committed to git).

Usage:
  python3 scripts/dwarkesh/fetch_transcripts.py --out-dir /tmp/dwarkesh_cache --limit 30
  python3 scripts/dwarkesh/fetch_transcripts.py --slugs paul-christiano-2 dario-amodei-2
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = "https://www.dwarkesh.com"
UA = "bayes-market-dwarkesh-transcripts/1.0 (+https://futarchy.ai; text-only)"

# Documented non-AI history / general-relativity episodes excluded from AI-futures curation
EXCLUDED_NON_AI_SLUGS: dict[str, str] = {
    "robert-caro": "Non-AI history biography (LBJ / Robert Moses).",
    "lessons-in-power": "Non-AI political history synthesis (Robert Caro / LBJ).",
    "si-sheppard": "Non-AI military/ancient history (Roman Republic / Pharsalus).",
    "adam-brown-gr": "Non-AI theoretical physics lecture (General Relativity).",
    "ada-palmer": "Non-AI Renaissance & censorship history.",
    "ada-palmer-2": "Non-AI Renaissance & institutional history.",
    "david-reich-2": "Non-AI ancient DNA & human prehistory.",
}


class _HTMLToText(HTMLParser):
    """Lightweight stdlib HTML-to-text extractor (skips scripts/styles/media)."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "audio", "video", "iframe"}
    BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and t in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and t in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t\r]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html_body: str) -> str:
    parser = _HTMLToText()
    parser.feed(html_body or "")
    parser.close()
    return parser.get_text()


def fetch_json(url: str, timeout: int = 25) -> object:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_recent_posts(limit: int, delay: float) -> list[dict]:
    posts: list[dict] = []
    offset = 0
    page_size = min(50, max(1, limit))
    while len(posts) < limit:
        url = f"{BASE_URL}/api/v1/posts?limit={page_size}&offset={offset}"
        batch = fetch_json(url)
        if not isinstance(batch, list) or not batch:
            break
        posts.extend(batch)
        if len(batch) < page_size:
            break
        offset += len(batch)
        if delay > 0:
            time.sleep(delay)
    return posts[:limit]


def fetch_post_text(slug: str) -> dict:
    url = f"{BASE_URL}/api/v1/posts/{slug}"
    post = fetch_json(url)
    assert isinstance(post, dict), f"Unexpected payload for {slug}"
    body_html = post.get("body_html") or ""
    text = html_to_text(body_html)
    return {
        "slug": slug,
        "title": post.get("title") or slug,
        "subtitle": post.get("subtitle") or "",
        "post_date": (post.get("post_date") or "")[:10],
        "canonical_url": post.get("canonical_url") or f"{BASE_URL}/p/{slug}",
        "word_count": len(text.split()),
        "text": text,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch Dwarkesh Substack text transcripts (text-only).")
    ap.add_argument("--out-dir", default="/tmp/dwarkesh_transcripts_cache")
    ap.add_argument("--limit", type=int, default=30, help="Number of recent posts to inspect when --slugs is omitted.")
    ap.add_argument("--slugs", nargs="*", help="Explicit post slugs to fetch.")
    ap.add_argument("--delay", type=float, default=0.5, help="Polite delay between requests (seconds).")
    ap.add_argument("--include-excluded", action="store_true", help="Also fetch documented non-AI history episodes.")
    ap.add_argument("--force", action="store_true", help="Refetch even if cached locally.")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.slugs:
        slugs = list(args.slugs)
    else:
        recent = list_recent_posts(args.limit, args.delay)
        slugs = [p["slug"] for p in recent if isinstance(p, dict) and p.get("slug")]

    fetched_count = 0
    skipped_excluded = 0
    cached_count = 0
    index_rows: list[dict] = []

    for slug in slugs:
        if not args.include_excluded and slug in EXCLUDED_NON_AI_SLUGS:
            skipped_excluded += 1
            continue
        txt_path = out_dir / f"{slug}.txt"
        meta_path = out_dir / f"{slug}.meta.json"
        if txt_path.exists() and meta_path.exists() and not args.force:
            meta = json.loads(meta_path.read_text())
            index_rows.append(meta)
            cached_count += 1
            continue
        try:
            rec = fetch_post_text(slug)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"WARN: failed to fetch {slug}: {exc}")
            continue
        text = rec.pop("text")
        txt_path.write_text(text + "\n", encoding="utf-8")
        meta_path.write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
        index_rows.append(rec)
        fetched_count += 1
        print(f"fetched {slug} ({rec['post_date']}, {rec['word_count']} words)")
        if args.delay > 0:
            time.sleep(args.delay)

    (out_dir / "index.json").write_text(
        json.dumps(
            {
                "source": BASE_URL,
                "mode": "text-only",
                "excludedNonAiSlugs": EXCLUDED_NON_AI_SLUGS,
                "episodes": index_rows,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"done: fetched={fetched_count}, cached={cached_count}, "
        f"skipped_non_ai={skipped_excluded}, out_dir={out_dir}"
    )


if __name__ == "__main__":
    main()
