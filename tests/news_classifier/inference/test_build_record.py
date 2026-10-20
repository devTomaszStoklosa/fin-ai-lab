from pathlib import Path

import pytest

from fin_ai_lab.news_classifier.inference.build_record import (
    adapter_fingerprint,
    discard_stale,
    is_built_from,
    note_path,
    record_built_from,
)


def _adapter(tmp_path: Path, weights: bytes = b"weights-v1") -> Path:
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir(exist_ok=True)
    (adapter_dir / "adapter_config.json").write_text('{"r": 8}', encoding="utf-8")
    (adapter_dir / "adapter_model.safetensors").write_bytes(weights)
    return adapter_dir


def _output(tmp_path: Path) -> Path:
    output = tmp_path / "model.gguf"
    output.write_bytes(b"gguf")
    return output


def test_output_built_from_same_adapter_is_current(tmp_path: Path) -> None:
    fingerprint = adapter_fingerprint(_adapter(tmp_path))
    output = _output(tmp_path)
    record_built_from(output, fingerprint)

    assert is_built_from(output, adapter_fingerprint(_adapter(tmp_path)))


def test_retrained_adapter_makes_output_stale(tmp_path: Path) -> None:
    old_fingerprint = adapter_fingerprint(_adapter(tmp_path, b"weights-v1"))
    output = _output(tmp_path)
    record_built_from(output, old_fingerprint)

    new_fingerprint = adapter_fingerprint(_adapter(tmp_path, b"weights-v2"))

    assert new_fingerprint != old_fingerprint
    assert not is_built_from(output, new_fingerprint)


def test_renamed_adapter_file_changes_fingerprint(tmp_path: Path) -> None:
    adapter_dir = _adapter(tmp_path)
    before = adapter_fingerprint(adapter_dir)
    (adapter_dir / "adapter_config.json").rename(adapter_dir / "other_config.json")

    assert adapter_fingerprint(adapter_dir) != before


def test_output_without_note_is_stale(tmp_path: Path) -> None:
    # Built before these notes existed, or left half-written by a crash.
    fingerprint = adapter_fingerprint(_adapter(tmp_path))

    assert not is_built_from(_output(tmp_path), fingerprint)


def test_note_without_output_is_stale(tmp_path: Path) -> None:
    fingerprint = adapter_fingerprint(_adapter(tmp_path))
    output = tmp_path / "model.gguf"
    record_built_from(output, fingerprint)

    assert not is_built_from(output, fingerprint)


@pytest.mark.parametrize("make_dir", [False, True])
def test_missing_or_empty_adapter_raises(tmp_path: Path, make_dir: bool) -> None:
    adapter_dir = tmp_path / "adapter"
    if make_dir:
        adapter_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="No adapter files"):
        adapter_fingerprint(adapter_dir)


def test_discard_stale_removes_directory_output_and_its_note(tmp_path: Path) -> None:
    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "model.safetensors").write_bytes(b"merged")
    record_built_from(merged, "abc")

    discard_stale(merged)

    assert not merged.exists()
    assert not note_path(merged).exists()


def test_discard_stale_removes_file_output_and_its_note(tmp_path: Path) -> None:
    output = _output(tmp_path)
    record_built_from(output, "abc")

    discard_stale(output)

    assert not output.exists()
    assert not note_path(output).exists()


def test_discard_stale_with_nothing_there_is_a_no_op(tmp_path: Path) -> None:
    discard_stale(tmp_path / "model.gguf")

    assert list(tmp_path.iterdir()) == []
