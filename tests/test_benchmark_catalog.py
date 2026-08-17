from pathlib import Path

from llm_pipeline.ui.benchmark_catalog import (
    discover_benchmark_catalog,
    option_count,
    project_names,
)


def test_discovers_bugsinpy_project_metadata(tmp_path: Path) -> None:
    bug_dir = tmp_path / "tools" / "BugsInPy" / "projects" / "httpie" / "bugs" / "1"
    bug_dir.mkdir(parents=True)

    catalog = discover_benchmark_catalog(tmp_path)

    assert catalog["bugsinpy"].projects["httpie"] == ["1"]
    assert option_count(catalog["bugsinpy"].projects) == 1


def test_discovers_defects4j_active_bugs_csv(tmp_path: Path) -> None:
    project_dir = tmp_path / "tools" / "defects4j" / "framework" / "projects" / "Chart"
    project_dir.mkdir(parents=True)
    (project_dir / "active-bugs.csv").write_text("1,2266,2264\n10,abc,def\n", encoding="utf-8")

    catalog = discover_benchmark_catalog(tmp_path)

    assert catalog["defects4j"].projects["Chart"] == ["1", "10"]


def test_project_names_are_stable() -> None:
    assert project_names({"Math": ["1"], "Chart": ["1"]}) == ["Chart", "Math"]
