from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from runproof import FileProbe, exec, run


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "a.txt"
        src.write_text("hello file probe\n", encoding="utf-8")

        with run("fileprobe-assert-demo") as ctx:
            exec(
                [
                    sys.executable,
                    "-c",
                    "import shutil; shutil.copyfile('a.txt', 'b.txt')",
                ],
                cwd=str(tmp_path),
                name="copy-a-to-b",
                probes=[FileProbe("b.txt", level=1, expect={"exists": True})],
            )

            exec(
                [sys.executable, "-c", "pass"],
                cwd=str(tmp_path),
                name="expect-missing-file",
                probes=[FileProbe("missing.txt", expect={"exists": True}, on_mismatch="fail_step")],
            )

        print(f"Receipt written to: {ctx.receipt_path}")
        print(f"View with: runproof view {ctx.receipt_path}")


if __name__ == "__main__":
    main()
