#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search uploaded Ruankao thesis textbooks for candidate directions and angles."
    )
    parser.add_argument("terms", nargs="+", help="Keywords for textbook search.")
    parser.add_argument("--vault", default=".", help="Vault or workspace root path.")
    parser.add_argument(
        "--textbook",
        default="",
        help="Optional explicit textbook PDF path. Defaults to the first PDF under 软考/资料/教材 matching 论文/写作/必背/押题.",
    )
    parser.add_argument(
        "--limit", type=int, default=5, help="Maximum number of candidate blocks."
    )
    return parser.parse_args()


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def unique_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in terms:
        for part in re.split(r"[，,、；;|/]+", raw):
            term = part.strip()
            key = normalize(term)
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(term)
    return cleaned


def find_textbook(vault: Path, explicit: str = "") -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    textbook_dir = vault / "软考/资料/教材"
    candidates = sorted(textbook_dir.glob("*.pdf"))
    preferred = [
        path
        for path in candidates
        if any(token in path.name for token in ("论文", "写作", "必背", "押题"))
    ]
    if preferred:
        return preferred[0]
    if candidates:
        return candidates[0]
    return textbook_dir / "请上传论文教材.pdf"


def extract_lines(pdf_path: Path) -> list[str]:
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "pdftotext failed")
    watermark_tokens = {"版", "盗", "权", "封", "知", "识", "产", "备", "案", "号"}
    cleaned: list[str] = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in watermark_tokens:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        cleaned.append(line)
    return cleaned


def match_terms(text: str, terms: list[str]) -> list[str]:
    compact = normalize(text)
    return [term for term in terms if normalize(term) in compact]


def find_anchor(lines: list[str], index: int) -> int | None:
    for cursor in range(index, max(-1, index - 20), -1):
        line = lines[cursor].strip()
        if not line:
            continue
        if "【方向" in line or re.search(r"角度\s*\d+", line):
            return cursor
        if re.search(r"论点\s*\d+", line) and "论点对应段落" not in line:
            return cursor
    return None


def block_score(block: list[str], terms: list[str], matched: list[str]) -> int:
    score = len(matched) * 8
    joined = "\n".join(block)
    if "【方向" in joined:
        score += 5
    if re.search(r"角度\s*\d+", joined):
        score += 4
    if re.search(r"论点\s*\d+", joined):
        score += 2
    if "实践落点" in joined:
        score += 2
    for line in block:
        score += len(match_terms(line, terms))
    return score


def collect_candidates(lines: list[str], terms: list[str]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen_keys: set[str] = set()

    for index, line in enumerate(lines):
        matched = match_terms(line, terms)
        if not matched:
            continue

        anchor = find_anchor(lines, index)
        start = max(0, (anchor if anchor is not None else index) - 2)
        end = min(len(lines), max(index + 7, (anchor if anchor is not None else index) + 8))
        block = [entry.rstrip() for entry in lines[start:end] if entry.strip()]
        if not block:
            continue

        key = normalize("".join(block[:4]))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        candidates.append(
            {
                "line": index + 1,
                "matched": matched,
                "score": block_score(block, terms, matched),
                "block": block,
            }
        )

    candidates.sort(
        key=lambda item: (
            int(item["score"]),
            len(item["matched"]),  # type: ignore[arg-type]
            -int(item["line"]),
        ),
        reverse=True,
    )
    return candidates


def print_candidates(candidates: list[dict[str, object]], limit: int) -> None:
    if not candidates:
        print("No candidates found. Try broader or adjacent-chapter keywords.", file=sys.stderr)
        sys.exit(1)

    for idx, candidate in enumerate(candidates[:limit], start=1):
        matched = ", ".join(candidate["matched"])  # type: ignore[arg-type]
        print(f"候选 {idx} | 行号 {candidate['line']} | 命中: {matched}")
        print(f"评分: {candidate['score']}")
        print("上下文:")
        for line in candidate["block"]:  # type: ignore[index]
            print(f"  {line}")
        if idx != min(limit, len(candidates)):
            print()


def main() -> int:
    args = parse_args()
    terms = unique_terms(args.terms)
    vault = Path(args.vault).expanduser().resolve()
    pdf_path = find_textbook(vault, args.textbook)
    if not pdf_path.exists():
        print(f"Textbook PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    try:
        lines = extract_lines(pdf_path)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1

    candidates = collect_candidates(lines, terms)
    print_candidates(candidates, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
