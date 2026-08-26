"""
LaunchPad-AI — Relevance Curator eval runner.

Calls the REAL curator (real Vertex AI — a handful of small requests)
against all 10 labeled cases in curator_cases.py and reports a pass rate.
This is informational, not a hard gate: LLM output is probabilistic even at
low temperature, so a single flaky case here isn't a build break. The two
canary cases are ALSO asserted as hard pytest failures in
test_curator_canaries.py — those must always pass.

Requires GOOGLE_GENAI_USE_VERTEXAI=1, GOOGLE_CLOUD_PROJECT,
GOOGLE_CLOUD_LOCATION, GEMINI_MODEL (or the gemini-3.5-flash default), and
application-default credentials with Vertex AI access
(`gcloud auth application-default login`).

Run from the repo root:

    python -m eval.run_curator_eval
"""

from __future__ import annotations

from agent.subagents.relevance_curator import curate
from eval.curator_cases import CASES


def main() -> None:
    passed = 0
    for case in CASES:
        decision = curate(case["profile"], case["memory_context"], delivery_id=f"eval-{case['name']}")
        ok = decision["action"] == case["expected_action"]
        passed += int(ok)
        marker = "PASS" if ok else "FAIL"
        canary = " [CANARY]" if case["canary"] else ""
        print(f"{marker}{canary} {case['name']}: expected={case['expected_action']} got={decision['action']}")
        if not ok:
            print(f"       reasoning: {decision.get('reasoning')!r}")

    total = len(CASES)
    print(f"\n{passed}/{total} passed ({passed / total:.0%})")


if __name__ == "__main__":
    main()
