import importlib.metadata

from typer.testing import CliRunner

from fin_ai_lab.cli import app

runner = CliRunner()


def test_version_command_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == importlib.metadata.version("fin-ai-lab")


def _build_result(indexed: bool):
    from fin_ai_lab.filings_rag.index.builder import CompanyBuildStatus, IndexBuildResult
    from fin_ai_lab.filings_rag.index.store import VectorStore
    from fin_ai_lab.filings_rag.models import Chunk

    store = VectorStore()
    statuses = [CompanyBuildStatus(company="Atrem", skipped_reason="FileNotFoundError: x.pdf")]
    if indexed:
        chunk = Chunk(
            id="m1",
            company="Microsoft",
            filing_type="10-K",
            fiscal_period="FY2026",
            section="ITEM 1A. RISK FACTORS",
            text="AI risk.",
            source_location="https://example.test/filing.htm",
            language="en",
        )
        store.add([chunk], [[1.0, 0.0]])
        statuses.insert(0, CompanyBuildStatus(company="Microsoft", chunk_count=1))
    return IndexBuildResult(store=store, statuses=statuses)


def test_filings_rag_build_index_saves_the_index_and_reports_skipped_companies(
    tmp_path, monkeypatch
) -> None:
    from fin_ai_lab import cli
    from fin_ai_lab.filings_rag.index.persist import load_index

    async def fake_build_index(loaders, **kwargs):
        return _build_result(indexed=True)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("SEC_USER_AGENT", "test agent test@example.test")
    monkeypatch.setattr(cli, "build_index", fake_build_index)
    output = tmp_path / "index.npz"

    result = runner.invoke(app, ["filings-rag", "build-index", "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert "Microsoft: indexed (1 chunks)" in result.output
    assert "Atrem: skipped (FileNotFoundError: x.pdf)" in result.output
    assert "1 of 2 companies, 1 chunks" in result.output
    saved = load_index(output)
    assert saved is not None
    assert [chunk.id for chunk in saved.store.chunks] == ["m1"]


def test_filings_rag_build_index_leaves_the_saved_index_alone_when_nothing_was_indexed(
    tmp_path, monkeypatch
) -> None:
    from fin_ai_lab import cli

    async def fake_build_index(loaders, **kwargs):
        return _build_result(indexed=False)

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("SEC_USER_AGENT", "test agent test@example.test")
    monkeypatch.setattr(cli, "build_index", fake_build_index)
    output = tmp_path / "index.npz"
    output.write_bytes(b"earlier index")

    result = runner.invoke(app, ["filings-rag", "build-index", "--output", str(output)])

    assert result.exit_code == 1
    assert output.read_bytes() == b"earlier index"
