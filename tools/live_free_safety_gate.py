"""Static fail-closed gate for the live free FutureEval runner/workflow."""
from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "live_free_runner.py"
WORKFLOW = ROOT / ".github" / "workflows" / "run_live_free.yaml"
CANARY = ROOT / ".github" / "workflows" / "run_live_free_canary.yaml"

def die(msg):
    print("LIVE_FREE_SAFETY_GATE FAIL:", msg)
    raise SystemExit(1)

def main():
    if not RUNNER.exists():
        die("runner missing")
    s = RUNNER.read_text(encoding="utf-8")
    ast.parse(s)
    required = [
        'ALLOWED_MODEL = "openrouter/free"',
        'SDK_MODEL_NAME = "openrouter/openrouter/free"',
        "predictions_per_research_report=1",
        "allowed_tries=1",
        "estimated_model_calls_this_run",
        "RERUN_BLOCKED_CHECK_EXISTING_RECEIPT",
        "READBACK_NOT_CONFIRMED_DO_NOT_RETRY",
        "fall-futureeval-2026",
        "minibench",
    ]
    for x in required:
        if x not in s:
            die("missing guard: " + x)
    for x in ("gpt-4o", "claude-sonnet", "sonar-pro", "gemini-2.5-pro"):
        if x in s:
            die("paid model token present: " + x)
    if "structure_output(" in s:
        die("parser call path present; would add model calls")
    if "MAX_RUNS_PER_UTC_DAY = 24" not in s:
        die("daily run cap is not 24")

    workflow = WORKFLOW if WORKFLOW.exists() else CANARY
    if not workflow.exists():
        die("workflow missing")
    w = workflow.read_text(encoding="utf-8")
    for secret in ("METACULUS_TOKEN", "OPENROUTER_API_KEY"):
        if secret not in w:
            die("required secret injection missing: " + secret)
    for forbidden in (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "PERPLEXITY_API_KEY",
        "EXA_API_KEY", "ASKNEWS_SECRET", "GOOGLE_API_KEY"
    ):
        if forbidden in w:
            die("forbidden provider secret in workflow: " + forbidden)
    if "uv sync --locked --no-dev" not in w:
        die("locked dependency install missing")
    if "timeout-minutes:" not in w:
        die("job timeout missing")
    if "concurrency:" not in w:
        die("concurrency missing")
    print("LIVE_FREE_SAFETY_GATE PASS")

if __name__ == "__main__":
    main()
