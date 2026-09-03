#!/usr/bin/env python3
"""
verify_metrics_reproducible.py
==============================
Proves the headline-number reduction is reproducible: for each released run under
``outputs/bionlp_eval*/``, re-run ``compute_bionlp_metrics.py`` from the committed
per-claim CSVs into a throwaway temp directory and assert the regenerated
``metrics.json`` is byte-identical to the committed one.

This is the machine-checkable form of REPRODUCIBILITY.md's claim that "a reviewer can
skip steps 1-4 and verify the numbers directly." The reduction reads only committed
inputs (claim_review.csv, summaries.csv, retrieval_discipline.csv, evidence_bundles/)
and must not depend on the ambient environment, so this check runs with and without
OPENAI_API_KEY set and requires both to match the committed output.

Exit code 0 == every run reproduces; non-zero == at least one mismatch.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUTS = REPO_ROOT / "outputs"

# Inputs the reduction consumes (metrics.json is the output, excluded on purpose).
INPUT_FILES = ("claim_review.csv", "summaries.csv", "retrieval_discipline.csv")
INPUT_DIRS = ("evidence_bundles",)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compute_bionlp_metrics  # noqa: E402


def run_dirs() -> list[Path]:
    return sorted(
        p for p in OUTPUTS.glob("bionlp_eval*")
        if (p / "claim_review.csv").exists() and (p / "metrics.json").exists()
    )


def regenerate_into_temp(run_dir: Path) -> str:
    """Copy the committed inputs into a temp dir, run the reduction, return the JSON text."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for name in INPUT_FILES:
            src = run_dir / name
            if src.exists():
                shutil.copy2(src, tmp_dir / name)
        for name in INPUT_DIRS:
            src = run_dir / name
            if src.exists():
                shutil.copytree(src, tmp_dir / name)
        # Suppress the reduction's stdout chatter.
        devnull = open(os.devnull, "w")
        old_stdout = sys.stdout
        try:
            sys.stdout = devnull
            compute_bionlp_metrics.main(out_dir=tmp_dir)
        finally:
            sys.stdout = old_stdout
            devnull.close()
        return (tmp_dir / "metrics.json").read_text(encoding="utf-8")


def main() -> int:
    dirs = run_dirs()
    if not dirs:
        print("No run directories with claim_review.csv found under outputs/.")
        return 1

    # Verify determinism under both env states: the reduction must ignore OPENAI_API_KEY.
    env_states = [("no-key", None), ("with-key", "sk-verify-dummy")]

    all_ok = True
    print(f"Verifying {len(dirs)} released run(s) reproduce their committed metrics.json\n")
    for run_dir in dirs:
        committed = (run_dir / "metrics.json").read_text(encoding="utf-8")
        rel = run_dir.relative_to(REPO_ROOT)
        row_ok = True
        for label, key in env_states:
            saved = os.environ.get("OPENAI_API_KEY")
            try:
                if key is None:
                    os.environ.pop("OPENAI_API_KEY", None)
                else:
                    os.environ["OPENAI_API_KEY"] = key
                regenerated = regenerate_into_temp(run_dir)
            finally:
                if saved is None:
                    os.environ.pop("OPENAI_API_KEY", None)
                else:
                    os.environ["OPENAI_API_KEY"] = saved
            if regenerated != committed:
                row_ok = False
                all_ok = False
                print(f"  MISMATCH  {rel}  [env={label}]")
        if row_ok:
            print(f"  OK        {rel}")

    print()
    if all_ok:
        print(f"PASS: all {len(dirs)} runs reproduce byte-identical metrics.json "
              f"(deterministic across OPENAI_API_KEY presence).")
        return 0
    print("FAIL: at least one run did not reproduce. See MISMATCH lines above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
