"""Eval suite for the BillRx audit pipeline.

Each case in evals/cases/ is a bill + EOB with the expected candidate findings
and the expected Reviewer verdicts. The checker must find exactly the expected
candidates; the Reviewer must reach the expected verdicts.

  python -m evals.run_evals                    # mock reviewer, must score 100%
  MODEL_PROVIDER=bedrock python -m evals.run_evals --min-verdict-accuracy 0.85

Results are written to evals/results/ with the model id, so a prompt or model
change can be compared run against run. CI runs the mock suite on every PR.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.llm import get_model_id, get_provider  # noqa: E402
from src.pipeline import Pipeline  # noqa: E402

CASES = ROOT / "evals" / "cases"
RESULTS = ROOT / "evals" / "results"


def run_case(case: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        b, e = Path(tmp) / "bill.json", Path(tmp) / "eob.json"
        b.write_text(json.dumps(case["bill"]))
        e.write_text(json.dumps(case["eob"]))
        started = time.perf_counter()
        res = Pipeline().run(b, e)
        seconds = time.perf_counter() - started
    got = sorted(c.finding_id for c in res.candidates)
    want = case["expected"]["candidates"]
    verdicts = {r.candidate.finding_id: r.verdict for r in res.reviewed}
    verdict_hits = {fid: verdicts.get(fid) == v for fid, v in case["expected"]["verdicts"].items()}
    no_tool = [r.candidate.finding_id for r in res.reviewed if not r.tools_called]
    return {
        "name": case["name"],
        "candidates_ok": got == want,
        "missing": sorted(set(want) - set(got)),
        "unexpected": sorted(set(got) - set(want)),
        "verdicts": verdicts,
        "verdict_hits": verdict_hits,
        "decisions_without_tools": no_tool,
        "seconds": round(seconds, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-verdict-accuracy", type=float, default=1.0)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    cases = [json.loads(p.read_text()) for p in sorted(CASES.glob("*.json"))]
    results = [run_case(c) for c in cases]

    hits = [h for r in results for h in r["verdict_hits"].values()]
    verdict_acc = sum(hits) / len(hits) if hits else 1.0
    cand_ok = all(r["candidates_ok"] for r in results)
    tools_ok = all(not r["decisions_without_tools"] for r in results)

    for r in results:
        flag = "PASS" if r["candidates_ok"] and all(r["verdict_hits"].values()) else "FAIL"
        extra = ""
        if r["missing"] or r["unexpected"]:
            extra += f" missing={r['missing']} unexpected={r['unexpected']}"
        bad = [k for k, ok in r["verdict_hits"].items() if not ok]
        if bad:
            extra += f" wrong_verdicts={bad}"
        print(f"{flag}  {r['name']}{extra}")
    print(f"\nprovider={get_provider()} model={get_model_id() if get_provider() == 'bedrock' else 'scripted'}")
    print(f"candidate detection: {'exact' if cand_ok else 'MISMATCH'}")
    print(f"verdict accuracy: {verdict_acc:.0%} (threshold {args.min_verdict_accuracy:.0%})")
    print(f"every decision used a tool: {tools_ok}")

    if not args.no_save:
        RESULTS.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        (RESULTS / f"{stamp}-{get_provider()}.json").write_text(json.dumps({
            "provider": get_provider(),
            "model": get_model_id() if get_provider() == "bedrock" else None,
            "verdict_accuracy": verdict_acc, "candidates_exact": cand_ok,
            "tools_always_used": tools_ok, "cases": results}, indent=2))

    ok = cand_ok and tools_ok and verdict_acc >= args.min_verdict_accuracy
    return 0 if ok else 1


if __name__ == "__main__":
    os.environ.setdefault("MODEL_PROVIDER", "mock")
    sys.exit(main())
