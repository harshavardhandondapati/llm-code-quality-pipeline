from __future__ import annotations

import os
import shutil
import subprocess
import sys


def run_command(command: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
        output = completed.stdout.strip()
        return completed.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    print("Java / Defects4J setup verification")
    print("===================================")

    java_path = shutil.which("java")
    javac_path = shutil.which("javac")
    defects4j_path = (
        os.environ.get("PIPELINE_DEFECTS4J_EXECUTABLE_DIRECTORY", "").rstrip("/")
    )

    if defects4j_path:
        defects4j_command = os.path.join(defects4j_path, "defects4j")
    else:
        defects4j_command = shutil.which("defects4j")

    checks_ok = True

    if java_path:
        print(f"java command: OK - {java_path}")
    else:
        print("java command: FAILED - missing")
        checks_ok = False

    if javac_path:
        print(f"javac command: OK - {javac_path}")
    else:
        print("javac command: FAILED - missing")
        checks_ok = False

    if defects4j_command and os.path.exists(defects4j_command):
        print(f"defects4j command: OK - {defects4j_command}")
    else:
        print("defects4j command: FAILED - missing")
        checks_ok = False
        defects4j_command = None

    if java_path:
        ok, output = run_command(["java", "-version"])
        print(f"java -version: {'OK' if ok else 'FAILED'} - {output.splitlines()[0] if output else ''}")
        checks_ok = checks_ok and ok

    if javac_path:
        ok, output = run_command(["javac", "-version"])
        print(f"javac -version: {'OK' if ok else 'FAILED'} - {output.splitlines()[0] if output else ''}")
        checks_ok = checks_ok and ok

    if defects4j_command:
        ok, output = run_command([defects4j_command, "info", "-p", "Chart"])
        if ok and "Project ID: Chart" in output:
            print("defects4j info -p Chart: OK")
        else:
            print(f"defects4j info -p Chart: FAILED - {output[:300]}")
            checks_ok = False

    print()

    if checks_ok:
        print("Java and Defects4J setup is ready.")
        return 0

    print("Java/Defects4J setup is not ready.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
