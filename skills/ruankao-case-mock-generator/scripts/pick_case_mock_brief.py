#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path


BANK_PATH = Path("软考/输出/案例冲刺/题库.json")
REAL_INDEX_PATH = Path("软考/输出/案例冲刺/真题索引.json")
GENERIC_TOKENS = {
    "上篇",
    "下篇",
    "系统",
    "设计",
    "架构",
    "分析",
    "简介",
    "概念",
    "案例",
    "方法",
    "模式",
    "原理",
    "实现",
    "问题",
    "应用",
    "技术",
    "题型",
}

CATEGORY_RULES = {
    "数据库系统与缓存设计": ("redis", "mysql", "缓存", "分片", "分区", "事务", "主从", "cluster", "持久化", "数据库", "es", "bson", "geojson", "哨兵"),
    "系统设计与建模": ("uml", "dfd", "e-r", "er图", "用例", "类图", "顺序图", "活动图", "状态图", "数据流图", "结构化分析", "面向对象", "建模"),
    "系统架构设计与评估": ("质量属性", "atam", "saam", "风格", "微服务", "分层", "架构评估", "可用性", "可修改性", "互操作性", "soa", "插件式"),
    "Web应用设计": ("web", "首页", "推荐", "feed", "kafka", "上传", "热点", "秒杀", "短视频", "网关", "并发"),
    "嵌入式系统架构设计": ("嵌入式", "传感器", "控制器", "总线", "终端", "硬件"),
    "系统安全": ("安全", "加密", "证书", "签名", "鉴权", "审计", "权限", "访问控制"),
    "项目管理": ("项目", "进度", "成本", "风险", "沟通", "干系人", "估算"),
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def tokenize(*parts: str) -> list[str]:
    seen: list[str] = []
    for part in parts:
        for token in re.findall(r"[A-Za-z0-9.+#-]+|[\u4e00-\u9fff]{2,}", part):
            lowered = token.lower()
            if lowered in GENERIC_TOKENS or len(lowered) < 2:
                continue
            if lowered not in seen:
                seen.append(lowered)
    return seen


def topic_category(text: str) -> str:
    lowered = text.lower()
    tokens = set(tokenize(lowered))
    for category, keywords in CATEGORY_RULES.items():
        for keyword in keywords:
            key = keyword.lower()
            if re.search(r"[a-z0-9]", key):
                if key in tokens:
                    return category
            elif key in lowered:
                return category
    return "系统架构设计与评估"


def importance_bonus(text: str) -> int:
    if "超级重点" in text:
        return 6
    if "重点" in text:
        return 4
    if "次重点" in text:
        return 2
    return 1


def flatten_topics(bank: dict) -> list[dict]:
    items: list[dict] = []
    for chapter in bank.get("chapters", []):
        for topic in chapter.get("topics", []):
            text = " ".join(
                [
                    str(topic.get("chapter_title", "")),
                    str(topic.get("title", "")),
                    str(topic.get("heading", "")),
                ]
            )
            items.append(
                {
                    "topic_id": topic.get("topic_id"),
                    "chapter_title": topic.get("chapter_title", ""),
                    "title": topic.get("title", ""),
                    "heading": topic.get("heading", ""),
                    "importance": topic.get("importance", ""),
                    "score": int(topic.get("score", 0)) + importance_bonus(topic.get("importance", "")),
                    "depth": int(topic.get("depth", 0)),
                    "question_prompt": topic.get("question_prompt", ""),
                    "category": topic_category(text),
                }
            )
    return items


def filter_topics(items: list[dict], focus_terms: list[str]) -> list[dict]:
    if not focus_terms:
        return items
    filtered: list[dict] = []
    for item in items:
        haystack = normalize(" ".join([item["chapter_title"], item["title"], item["category"]])).lower()
        if any(term in haystack for term in focus_terms):
            filtered.append(item)
    return filtered


def choose_topics(items: list[dict], count: int, rng: random.Random) -> list[dict]:
    pool = sorted(items, key=lambda item: (item["score"], item["depth"]), reverse=True)
    selected: list[dict] = []
    seen_topic_ids: set[str] = set()
    seen_categories: dict[str, int] = {}
    seen_chapters: dict[str, int] = {}

    while pool and len(selected) < count:
        best_index = 0
        best_value: tuple[float, float, float] | None = None
        for index, item in enumerate(pool):
            category_penalty = seen_categories.get(item["category"], 0) * 2.5
            chapter_penalty = seen_chapters.get(item["chapter_title"], 0) * 1.5
            diversity_bonus = 2.0 if item["category"] not in seen_categories else 0.0
            jitter = rng.random()
            value = (item["score"] - category_penalty - chapter_penalty + diversity_bonus, item["depth"], jitter)
            if best_value is None or value > best_value:
                best_value = value
                best_index = index

        chosen = pool.pop(best_index)
        if chosen["topic_id"] in seen_topic_ids:
            continue
        selected.append(chosen)
        seen_topic_ids.add(chosen["topic_id"])
        seen_categories[chosen["category"]] = seen_categories.get(chosen["category"], 0) + 1
        seen_chapters[chosen["chapter_title"]] = seen_chapters.get(chosen["chapter_title"], 0) + 1

    return selected


def match_real_cases(real_items: list[dict], topic: dict, limit: int) -> list[dict]:
    tokens = tokenize(topic["chapter_title"], topic["title"], topic["heading"])
    matches: list[tuple[tuple[int, int], dict]] = []

    for item in real_items:
        category_score = 3 if item.get("category") == topic["category"] else 0
        search_text = normalize(item.get("search_text", "")).lower()
        overlap = sum(1 for token in tokens if token in search_text)
        recency = int(item.get("year", 0)) * 100 + int(item.get("month", 0))
        score = (category_score + overlap, recency)
        if category_score or overlap:
            matches.append((score, item))

    if not matches:
        return []

    matches.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in matches[:limit]]


def problem_summary(item: dict) -> str:
    prompts = []
    for problem in item.get("problems", []):
        index = str(problem.get("index", "")).strip()
        prompt = normalize(problem.get("prompt", ""))
        if not prompt or not index.isdigit():
            continue
        prompts.append(f"（{index}）{prompt}")
        if len(prompts) == 2:
            break
    return "；".join(prompts)


def render_brief(mode: str, count: int, focus_terms: list[str], topics: list[dict], real_items: list[dict], source_bank: dict) -> str:
    lines = [
        "# ruankao-case-mock-generator简报",
        "",
        f"- 模式：`{mode}`",
        f"- 推荐题量：`{count}`",
        f"- 题库生成日期：`{source_bank.get('generated_at', 'unknown')}`",
        f"- 聚焦方向：`{', '.join(focus_terms) if focus_terms else '未指定'}`",
        "",
        "## 推荐命题组合",
        "",
    ]

    for index, topic in enumerate(topics, start=1):
        lines.append(f"### 题目 {index}")
        lines.append(f"- 类别：`{topic['category']}`")
        lines.append(f"- 章节：`{topic['chapter_title']}`")
        lines.append(f"- 知识点：`{topic['heading']} {topic['title']}`".rstrip())
        lines.append(f"- 重要度：`{topic['importance'] or '未标注'}`")
        lines.append(f"- 推荐小问骨架：{topic['question_prompt'].replace(chr(10), ' / ')}")

        matches = match_real_cases(real_items, topic, limit=2)
        if matches:
            for real in matches:
                lines.append(
                    "- 参考真题："
                    f"`{real.get('real_question_id')}` "
                    f"{real.get('exam_label')} / {real.get('category')} / {real.get('subject')}"
                )
                summary = problem_summary(real)
                if summary:
                    lines.append(f"- 真题问法参考：{summary}")
        else:
            lines.append("- 参考真题：未找到高匹配项，可按同类别真题风格人工命题")

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pick locally grounded topics and real-case references for Ruankao mock-case generation.")
    parser.add_argument("--vault", required=True, help="Vault root path")
    parser.add_argument("--mode", choices=("single", "mini", "full"), default="full")
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--focus", default="", help="Comma-separated focus terms")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def default_count(mode: str) -> int:
    if mode == "single":
        return 1
    if mode == "mini":
        return 3
    return 5


def main() -> int:
    args = parse_args()
    vault = Path(args.vault).expanduser().resolve()
    bank = load_json(vault / BANK_PATH)
    real_index = load_json(vault / REAL_INDEX_PATH)

    count = args.count or default_count(args.mode)
    focus_terms = [term.strip().lower() for term in args.focus.split(",") if term.strip()]
    rng = random.Random(args.seed)

    topics = flatten_topics(bank)
    topics = [topic for topic in topics if topic["depth"] >= 3] or topics
    topics = filter_topics(topics, focus_terms)
    if not topics:
        raise SystemExit("No topics matched the requested focus terms.")

    selected = choose_topics(topics, count=count, rng=rng)
    print(render_brief(args.mode, count, focus_terms, selected, real_index.get("items", []), bank))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
