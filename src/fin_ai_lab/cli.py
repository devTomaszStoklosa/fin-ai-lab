import importlib.metadata

import typer

app = typer.Typer()


@app.command()
def version() -> None:
    typer.echo(importlib.metadata.version("fin-ai-lab"))
