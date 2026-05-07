from pathlib import Path

from src.main import resolve_all_inputs


def test_resolve_all_inputs_combines_files_and_dirs(tmp_path):
    directory = tmp_path / "inputs"
    directory.mkdir()
    first = directory / "a.json"
    first.write_text("[]", encoding="utf-8")
    second = tmp_path / "b.json"
    second.write_text("[]", encoding="utf-8")

    paths = resolve_all_inputs([str(second)], [str(directory)])
    assert paths == [first.resolve(), second.resolve()]
