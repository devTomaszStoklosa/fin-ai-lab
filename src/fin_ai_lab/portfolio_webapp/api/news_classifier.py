"""News classifier endpoint: the P4 model comparison report."""

from fastapi import APIRouter

from fin_ai_lab.news_classifier.service import load_labeled as load_news_classifier_corpus
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.schemas import ComparisonReportOut


def _parse_markdown_table(markdown: str, heading: str) -> tuple[list[str], list[list[str]]]:
    """Generic pipe-table extractor -- doesn't hardcode column names, so a
    future column added to `comparison_report.render_comparison_report()`
    shows up here without a code change."""
    lines = markdown.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading) + 1
    except StopIteration:
        return [], []

    table_lines = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            if table_lines:
                break
            continue
        if stripped.startswith("|"):
            table_lines.append(stripped)
        elif table_lines:
            break
    if len(table_lines) < 2:
        return [], []

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    columns = cells(table_lines[0])
    rows = [cells(line) for line in table_lines[2:]]  # table_lines[1] is the "|---|" separator
    return columns, rows


def _parse_bullet_list(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading) + 1
    except StopIteration:
        return []

    notes = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("- "):
            notes.append(stripped[2:])
        elif notes:
            break
    return notes


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/news-classifier/comparison-report", response_model=ComparisonReportOut | None)
    def news_classifier_comparison_report() -> ComparisonReportOut | None:
        if not deps.comparison_report_path.exists():
            return None
        markdown = deps.comparison_report_path.read_text(encoding="utf-8")
        columns, rows = _parse_markdown_table(markdown, "## Podsumowanie")
        notes = _parse_bullet_list(markdown, "## Klasy bez wsparcia w zbiorze testowym")

        corpus = load_news_classifier_corpus(deps.news_classifier_corpus_path)
        latest_headline_date = max(
            (item.headline.published_at.date() for item in corpus), default=None
        )
        return ComparisonReportOut(
            columns=columns,
            rows=rows,
            zero_support_notes=notes,
            corpus_size=len(corpus),
            corpus_latest_headline_date=latest_headline_date,
        )

    return router
