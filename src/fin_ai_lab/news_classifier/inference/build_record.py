"""Records which LoRA adapter each output of
`scripts/news_classifier_quantize_bielik.py` was built from (issue #6).

Every step's output gets a sibling `<output>.adapter-sha256` note, written
only after that step succeeds. A step is skipped only when its note matches
the current adapter -- a retrained adapter, or an output with no note (built
before these notes existed, or left half-written by a crash), is rebuilt
instead of silently reused.

Standard library only, so the script can decide what to skip before it
imports the heavy `quantized` extra.
"""

import hashlib
import shutil
from pathlib import Path

NOTE_SUFFIX = ".adapter-sha256"
_CHUNK_SIZE = 1024 * 1024


def adapter_fingerprint(adapter_dir: Path) -> str:
    """SHA-256 over every file in `adapter_dir` -- relative path, size and
    contents, in a fixed order -- so any change to the adapter changes it."""
    files = [path for path in adapter_dir.rglob("*") if path.is_file()]
    if not files:
        raise FileNotFoundError(
            f"No adapter files in {adapter_dir} — copy the LoRA adapter there first"
        )

    digest = hashlib.sha256()
    for path in sorted(files, key=lambda path: path.relative_to(adapter_dir).as_posix()):
        # Name and size go in first, so file boundaries can't blur together.
        header = f"{path.relative_to(adapter_dir).as_posix()}\0{path.stat().st_size}\0"
        digest.update(header.encode("utf-8"))
        with path.open("rb") as file:
            while chunk := file.read(_CHUNK_SIZE):
                digest.update(chunk)
    return digest.hexdigest()


def note_path(output: Path) -> Path:
    return output.with_name(output.name + NOTE_SUFFIX)


def is_built_from(output: Path, fingerprint: str) -> bool:
    note = note_path(output)
    return (
        output.exists()
        and note.exists()
        and note.read_text(encoding="utf-8").strip() == fingerprint
    )


def discard_stale(output: Path) -> None:
    """Remove an output (file or directory) and its note before rebuilding.
    The note goes first, so an interrupted removal still counts as stale."""
    note_path(output).unlink(missing_ok=True)
    if output.is_dir():
        shutil.rmtree(output)
    else:
        output.unlink(missing_ok=True)


def record_built_from(output: Path, fingerprint: str) -> None:
    note_path(output).write_text(fingerprint + "\n", encoding="utf-8")
