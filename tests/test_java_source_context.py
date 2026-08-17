from pathlib import Path

from llm_pipeline.context.file_discovery import FileDiscovery
from llm_pipeline.context.source_context import SourceContextBuilder
from llm_pipeline.repair.apply_patch import _looks_like_java_source
from llm_pipeline.schemas import BugCase, CommandResult


def make_test_result(project: Path, output: str) -> CommandResult:
    return CommandResult(
        command=["defects4j", "test"],
        working_directory=project,
        return_code=1,
        stdout=output,
        stderr="",
        execution_time_seconds=0.1,
    )


def test_file_discovery_can_find_java_and_build_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = project / "src" / "main" / "java" / "Example.java"
    source.parent.mkdir(parents=True)
    source.write_text("public class Example {}\n", encoding="utf-8")
    (project / "pom.xml").write_text("<project/>\n", encoding="utf-8")
    (project / "README.md").write_text("ignore\n", encoding="utf-8")

    discovery = FileDiscovery(
        extensions=(".java", ".xml"),
        include_file_names=("pom.xml",),
    )

    names = [path.relative_to(project).as_posix() for path in discovery.discover(project)]

    assert names == ["pom.xml", "src/main/java/Example.java"]


def test_source_context_can_extract_java_failure_location(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = project / "src" / "main" / "java" / "Example.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "public class Example {\n"
        "  int divide(int a, int b) {\n"
        "    return a / b;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    bug_case = BugCase(
        dataset="Defects4J",
        project="Example",
        bug_id="1",
        language="java",
        workspace_path=project,
        metadata={"changed_files": ["src/main/java/Example.java"]},
    )
    builder = SourceContextBuilder(
        file_discovery=FileDiscovery(extensions=(".java",)),
        max_files=2,
        use_benchmark_hints=True,
    )

    context = builder.build(
        bug_case,
        make_test_result(project, "src/main/java/Example.java:3: failure"),
    )

    assert context.language == "java"
    assert context.snippets[0].file_path == "src/main/java/Example.java"
    assert "return a / b" in context.snippets[0].content


def test_java_fixed_file_guard_accepts_java_source() -> None:
    assert _looks_like_java_source("package demo;\npublic class Example {}\n") is True
    assert _looks_like_java_source("This is only an explanation, not source code") is False
