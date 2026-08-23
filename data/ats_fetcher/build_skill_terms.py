#!/usr/bin/env python
"""
Cross-reference the O*NET skill vocabulary against fetched postings and
curate the term list the stage 2 matcher reads.

Two modes:
  (default)  Scan postings.csv against ../onet/out/skill_vocabulary.csv and
             write skill_terms_review.csv — every candidate term, how often
             it fires against the real posting corpus, and flags for likely
             false positives.
  --filter   Read skill_terms_review.csv and write skill_terms.csv from the
             rows marked keep=y.

skill_terms_review.csv is the permanent record of every term ever considered
and the human decision on it — currently all 8,725 O*NET-derived terms,
whether or not they fired against any posting in this run. Those rows are
kept deliberately, not just the ones that matched, so that a future O*NET
vocabulary refresh can be diffed against this file and only genuinely new
terms need review, not the whole list again.

skill_terms.csv is generated output, regenerated on demand via --filter. It
is what the stage 2 matcher reads — not something to hand-edit.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS_PATH = HERE / ".." / "onet" / "out" / "skill_vocabulary.csv"
POSTINGS_PATH = HERE / "postings.csv"
REVIEW_PATH = HERE / "skill_terms_review.csv"
FILTERED_PATH = HERE / "skill_terms.csv"

STRIP_SUFFIXES = ["software", "systems", "system", "program", "tools", "tool"]

SHORT_TOKEN_MAX_LEN = 3
HIGH_FIRE_RATE_THRESHOLD = 0.15
CONTEXT_CHARS = 80

COMMON_WORDS = {
    "about", "access", "after", "again", "also", "analysis", "and", "any",
    "application", "are", "around", "as", "at", "base", "basic", "best",
    "but", "buy", "by", "call", "camera", "can", "care", "cloud", "code",
    "color", "community", "company", "complete", "content", "control",
    "copy", "create", "custom", "data", "day", "design", "develop",
    "digital", "direct", "do", "document", "draw", "drive", "easy", "edit",
    "end", "enterprise", "event", "every", "excel", "explorer", "export",
    "file", "files", "find", "first", "fix", "focus", "follow", "for",
    "form", "forms", "from", "full", "get", "go", "good", "group", "guide",
    "have", "health", "help", "home", "how", "image", "import", "in",
    "insight", "instant", "into", "is", "it", "just", "keep", "key", "know",
    "learn", "life", "like", "link", "list", "live", "local", "look",
    "made", "mail", "make", "manage", "management", "manager", "map",
    "maps", "mark", "market", "master", "match", "media", "meet",
    "meeting", "message", "mobile", "model", "more", "move", "my", "new",
    "news", "next", "note", "notes", "now", "number", "numbers", "of",
    "office", "ok", "on", "one", "online", "only", "open", "or", "order",
    "organize", "other", "out", "over", "page", "pages", "paint", "paper",
    "part", "pay", "people", "photo", "photos", "plan", "planner", "play",
    "plus", "point", "post", "power", "present", "print", "pro", "process",
    "product", "program", "project", "public", "read", "ready", "record",
    "report", "reports", "review", "run", "save", "scan", "search", "see",
    "send", "service", "set", "settings", "setup", "share", "show",
    "simple", "site", "size", "smart", "solution", "solutions", "sort",
    "source", "space", "speed", "sport", "start", "state", "step", "store",
    "story", "studio", "style", "support", "sync", "table", "tag", "take",
    "talk", "task", "tasks", "team", "teams", "tech", "text", "time",
    "tips", "top", "total", "touch", "track", "train", "transfer", "true",
    "try", "turn", "type", "update", "use", "user", "view", "vision",
    "visit", "voice", "wallet", "watch", "way", "weather", "web", "week",
    "well", "what", "when", "where", "which", "white", "who", "why",
    "will", "win", "with", "word", "work", "works", "world", "write",
    "year", "you", "your",
}


def normalize_term(raw_term):
    result = raw_term.strip()
    changed = True
    while changed:
        changed = False
        for suffix in STRIP_SUFFIXES:
            pattern = re.compile(rf"\s+{re.escape(suffix)}$", re.IGNORECASE)
            stripped = pattern.sub("", result)
            if stripped != result:
                result = stripped.strip()
                changed = True
    return result


def load_skill_terms(path):
    terms = {}
    skipped_empty = 0
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            raw_term = (row.get("product") or "").strip()
            if not raw_term:
                continue
            term = normalize_term(raw_term)
            if not term:
                skipped_empty += 1
                continue
            key = term.lower()
            if key not in terms:
                terms[key] = {
                    "term": term,
                    "category": (row.get("category") or "").strip(),
                    "hot_technology": (row.get("hot_technology") or "").strip(),
                }
    if skipped_empty:
        print(f"  skipped {skipped_empty} rows that normalized to empty")
    return list(terms.values())


def load_postings(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def flag_reason(term, fire_rate):
    if len(term) <= SHORT_TOKEN_MAX_LEN:
        return "short token"
    if term.lower() in COMMON_WORDS:
        return "common word"
    if fire_rate > HIGH_FIRE_RATE_THRESHOLD:
        return "high fire rate"
    return ""


def extract_example(text, match):
    half = CONTEXT_CHARS // 2
    start = max(0, match.start() - half)
    end = min(len(text), match.end() + half)
    snippet = text[start:end]
    return " ".join(snippet.split())


def run_generate():
    if not SKILLS_PATH.exists():
        sys.exit(f"skill vocabulary not found: {SKILLS_PATH}")
    if not POSTINGS_PATH.exists():
        sys.exit(f"postings not found: {POSTINGS_PATH}")

    print(f"reading {SKILLS_PATH}")
    skill_terms = load_skill_terms(SKILLS_PATH)
    print(f"  {len(skill_terms)} unique normalized terms")

    print(f"reading {POSTINGS_PATH}")
    postings = load_postings(POSTINGS_PATH)
    total_postings = len(postings)
    if total_postings == 0:
        sys.exit("no postings found")
    print(f"  {total_postings} postings")

    descriptions = [p.get("description") or "" for p in postings]

    print("scanning...")
    results = []
    for info in skill_terms:
        term = info["term"]
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        fire_count = 0
        examples = []
        for text in descriptions:
            if not text:
                continue
            match = pattern.search(text)
            if not match:
                continue
            fire_count += 1
            if len(examples) < 2:
                examples.append(extract_example(text, match))
        fire_rate = fire_count / total_postings
        reason = flag_reason(term, fire_rate)
        results.append({
            "term": term,
            "category": info["category"],
            "hot_technology": info["hot_technology"],
            "fire_count": fire_count,
            "fire_rate": f"{fire_rate:.4f}",
            "example_1": examples[0] if len(examples) > 0 else "",
            "example_2": examples[1] if len(examples) > 1 else "",
            "flag_reason": reason,
            "keep": "" if reason else "Y",
        })

    results.sort(key=lambda r: float(r["fire_rate"]), reverse=True)

    fieldnames = [
        "term", "category", "hot_technology", "fire_count", "fire_rate",
        "example_1", "example_2", "flag_reason", "keep",
    ]
    with REVIEW_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    fired = sum(1 for r in results if r["fire_count"] > 0)
    print(f"wrote {REVIEW_PATH.name}  ({len(results)} terms, {fired} fired at least once)")


def run_filter():
    if not REVIEW_PATH.exists():
        sys.exit(f"review file not found: {REVIEW_PATH}")

    with REVIEW_PATH.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    blank_terms = []
    kept_rows = []
    dropped = 0

    for row in rows:
        keep_value = (row.get("keep") or "").strip()
        if not keep_value:
            blank_terms.append(row.get("term", ""))
        elif keep_value.lower() == "y":
            kept_rows.append(row)
        else:
            dropped += 1

    if blank_terms:
        print(f"{len(blank_terms)} term(s) have no keep decision yet — refusing to write {FILTERED_PATH.name}:")
        for term in blank_terms:
            print(f"  {term}")
        sys.exit(1)

    with FILTERED_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["term", "category", "hot_technology"])
        writer.writeheader()
        for row in kept_rows:
            writer.writerow({
                "term": row["term"],
                "category": row["category"],
                "hot_technology": row["hot_technology"],
            })

    print(f"reviewed rows: {total}")
    print(f"kept:          {len(kept_rows)}")
    print(f"dropped:       {dropped}")
    print(f"blank:         0")
    print(f"wrote {FILTERED_PATH.name}  ({len(kept_rows)} terms)")


def main():
    parser = argparse.ArgumentParser(description="Build or filter the skill term vocabulary.")
    parser.add_argument(
        "--filter", action="store_true",
        help="Build skill_terms.csv from the reviewed skill_terms_review.csv instead of regenerating it.",
    )
    args = parser.parse_args()

    if args.filter:
        run_filter()
    else:
        run_generate()


if __name__ == "__main__":
    main()
