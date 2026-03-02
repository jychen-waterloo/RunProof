from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from runproof import exec, run, step


@step("required_success", required=True)
def required_success() -> dict:
    return {"ok": True, "message": "required step succeeded"}


@step("non_required_failure")
def non_required_failure() -> None:
    raise RuntimeError("intentional failure")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "source.txt"
        dst = Path(tmp) / "copy.txt"
        src.write_text("hello runproof", encoding="utf-8")

        with run("simple-example") as receipt_ctx:
            required_success()
            try:
                non_required_failure()
            except RuntimeError:
                pass
            exec(
                [
                    sys.executable,
                    "-c",
                    "import shutil,sys; shutil.copy2(sys.argv[1], sys.argv[2])",
                    str(src),
                    str(dst),
                ],
                expect_files=[str(dst)],
                name="copy-file",
            )

        print(f"Receipt written to: {receipt_ctx.receipt_path}")


if __name__ == "__main__":
    main()
