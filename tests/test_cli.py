import importlib.metadata

from typer.testing import CliRunner

from fin_ai_lab.cli import app

runner = CliRunner()


def test_version_command_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == importlib.metadata.version("fin-ai-lab")
