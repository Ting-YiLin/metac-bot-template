"""FutureEval S0: one eligible binary question in bot-testing-area only.

Requires the *official* metac-bot-template, forecasting-tools via pinned uv.lock,
Metaculus bot token and OpenRouter key supplied only by GitHub Actions Secrets.
No scheduled runs, no paid model identifiers, no external research calls.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_TOURNAMENT = "bot-testing-area"
ALLOWED_MODEL = "openrouter/free"        # OpenRouter's documented zero-priced router
SDK_MODEL_NAME = "openrouter/openrouter/free"  # LiteLLM provider prefix + router ID
OUTPUT = Path("s0_receipt_candidate.json")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_public_record(obj: dict) -> None:
    # Only non-sensitive, allowlisted fields. Never serialize responses or env.
    permitted = {
        "stage", "status", "reason_code", "timestamp_utc", "tournament",
        "model_routing_id", "question_post_id", "question_id", "question_url",
        "github_run_url", "github_sha", "submission_function_returned",
        "platform_readback_already_forecasted", "platform_readback_error_type",
        "report_type", "result_count"
    }
    OUTPUT.write_text(json.dumps({k: v for k, v in obj.items() if k in permitted},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check_question(q) -> bool:
    # Refuse every question not selected directly from the exact test tournament.
    # The caller must never submit any question obtained from another source.
    try:
        from forecasting_tools.data_models.questions import BinaryQuestion, QuestionState
        u = urlsplit(q.page_url)
        return (isinstance(q, BinaryQuestion)
                and q.state == QuestionState.OPEN
                and q.already_forecasted is False
                and u.scheme == "https"
                and u.hostname in ("www.metaculus.com", "metaculus.com")
                and isinstance(q.id_of_post, int))
    except (AttributeError, TypeError, ValueError):
        return False


def fail(code: str, base: dict) -> int:
    status = ("STOP_AMBIGUOUS_MAY_HAVE_SUBMITTED" if code.startswith("SUBMIT_AMBIGUOUS")
              else "STOP_BEFORE_SUBMISSION")
    save_public_record({**base, "status": status, "reason_code": code})
    print("S0 STOP: " + code)
    return 1


async def submit_once(question, client):
    from main import FallTemplateBot2026
    from forecasting_tools import GeneralLlm

    # Set ALL roles. SDK missing-role default could otherwise silently use paid models.
    def free_llm():
        return GeneralLlm(model=SDK_MODEL_NAME, temperature=0.2,
                          timeout=65, allowed_tries=1)

    class NoResearchOneShotBot(FallTemplateBot2026):
        async def run_research(self, question):
            return ("Connectivity verification only. No external web research. "
                    "Give a calibrated probability based only on the question "
                    "and its resolution criteria, with a short explanation.")

    bot = NoResearchOneShotBot(
        research_reports_per_question=1,
        predictions_per_research_report=1,
        enable_summarize_research=False,
        use_research_summary_to_forecast=False,
        publish_reports_to_metaculus=True,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=True,
        extra_metadata_in_explanation=False,
        required_successful_predictions=1.0,
        llms={role: free_llm() for role in ("default", "summarizer", "researcher", "parser")},
        metaculus_client=client,
    )
    roles = bot.make_llm_dict()
    # Guard against SDK changing the actual configured models.
    if not all(SDK_MODEL_NAME in str(roles.get(role))
               for role in ("default", "summarizer", "researcher", "parser")):
        raise RuntimeError("MODEL_ALLOWLIST_GUARD_FAILED")
    return await bot.forecast_question(question, return_exceptions=False)


def main() -> int:
    base = {
        "stage": "S0_T04", "timestamp_utc": now_utc(),
        "tournament": ALLOWED_TOURNAMENT, "model_routing_id": ALLOWED_MODEL,
        "github_run_url": (f"https://github.com/{os.getenv('GITHUB_REPOSITORY', 'Ting-YiLin/metac-bot-template')}"
                           f"/actions/runs/{os.getenv('GITHUB_RUN_ID', 'UNKNOWN')}"),
        "github_sha": os.getenv("GITHUB_SHA", "UNKNOWN"),
        "submission_function_returned": False,
        "platform_readback_already_forecasted": False,
    }
    # This script can only be triggered in the controlled Actions workflow,
    # not by an accidental local run in a repo with ambient credentials.
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("S0_TEST_ONLY") != "1":
        return fail("GITHUB_ACTIONS_TEST_GATE_MISSING", base)
    if os.getenv("GITHUB_RUN_ATTEMPT") != "1":
        return fail("RERUN_BLOCKED_CHECK_EXISTING_RECEIPT", base)
    if os.getenv("GITHUB_REPOSITORY") != "Ting-YiLin/metac-bot-template":
        return fail("REPOSITORY_NOT_ALLOWLISTED", base)
    if os.getenv("S0_FREE_MODEL") != ALLOWED_MODEL:
        return fail("MODEL_NOT_FREE_ROUTER", base)
    if not (os.getenv("METACULUS_TOKEN") and os.getenv("OPENROUTER_API_KEY")):
        return fail("NEED_USER_AUTH", base)

    # Check no privileged LLM/search-provider keys are available to the test job.
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ASKNEWS_CLIENT_ID",
                 "ASKNEWS_SECRET", "PERPLEXITY_API_KEY", "EXA_API_KEY"):
        if os.getenv(name):
            return fail("UNAPPROVED_PROVIDER_KEY_PRESENT", base)

    # Production forecasting code is never executed directly; only the SDK's
    # authenticated client from the official package is used.
    try:
        from forecasting_tools.helpers.metaculus_client import MetaculusClient
        client = MetaculusClient()
        questions = client.get_all_open_questions_from_tournament(ALLOWED_TOURNAMENT)
        eligible = sorted([q for q in questions if check_question(q)], key=lambda q: q.id_of_post)
    except Exception as e:
        return fail("FETCH_FAILED_" + type(e).__name__, base)

    if not eligible:
        return fail("NO_ELIGIBLE_UNFORECASTED_BINARY_TEST_QUESTION", base)
    q = eligible[0]
    base.update({"question_post_id": q.id_of_post,
                 "question_id": getattr(q, "id_of_question", None),
                 "question_url": q.page_url, "result_count": 1})
    # At most one invocation of the official publishing method.
    # If the call errors after a partial submit: STOP, inspect the bot's history.
    try:
        report = asyncio.run(submit_once(q, client))
        base["submission_function_returned"] = True
        base["report_type"] = type(report).__name__
    except Exception as e:
        return fail("SUBMIT_AMBIGUOUS_CHECK_PLATFORM_" + type(e).__name__, base)

    # Secondary authenticated readback (read-only), not a second submission.
    try:
        updated = client.get_question_by_post_id(q.id_of_post)
        base["platform_readback_already_forecasted"] = (
            getattr(updated, "already_forecasted", None) is True)
    except Exception as e:
        base["platform_readback_error_type"] = type(e).__name__
    base["timestamp_utc"] = now_utc()
    base["status"] = ("READBACK_INDICATES_PLATFORM_FORECAST"
                      if base["platform_readback_already_forecasted"]
                      else "PENDING_PLATFORM_ACCOUNT_CONFIRMATION")
    save_public_record(base)
    print("S0 test-only candidate record saved. Verify in Metaculus bot account.")
    print("Question:", base["question_url"])
    print("State:", base["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
