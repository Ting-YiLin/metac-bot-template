"""FutureEval live free baseline runner for Ting-Yi001.

Safety properties:
- Only Fall 2026 FutureEval and current MiniBench.
- Only open, unforecasted binary questions.
- Exactly one selected question per process; at most one LLM call for that question.
- Explicit OpenRouter free router for every LLM role; no paid/search provider envs.
- Fail closed on ambiguous submit; never auto-retry a possibly submitted question.
- Sanitized receipt only; never serializes secrets or Authorization headers.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_TOURNAMENTS = ("fall-futureeval-2026", "minibench")
ALLOWED_MODEL = "openrouter/free"
SDK_MODEL_NAME = "openrouter/openrouter/free"
OUTPUT = Path("live_free_receipt.json")
MIN_REMAINING_MINUTES = 10
MAX_RUNS_PER_UTC_DAY = 36
PROHIBITED_PROVIDER_ENVS = (
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ASKNEWS_CLIENT_ID", "ASKNEWS_SECRET",
    "PERPLEXITY_API_KEY", "EXA_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def save_public_record(obj: dict) -> None:
    permitted = {
        "stage", "status", "reason_code", "timestamp_utc", "tournament",
        "model_routing_id", "question_post_id", "question_id", "question_url",
        "github_run_url", "github_sha", "github_run_attempt",
        "submission_function_returned", "platform_readback_already_forecasted",
        "platform_readback_error_type", "report_type", "eligible_count",
        "openrouter_key_valid", "openrouter_is_free_tier", "openrouter_usage_daily_usd",
        "openrouter_limit_remaining_usd", "openrouter_rate_limit_requests",
        "estimated_model_calls_this_run", "daily_run_count", "max_daily_runs",
        "scheduled_close_time", "minutes_to_close", "selected_reason",
    }
    OUTPUT.write_text(
        json.dumps({k: v for k, v in obj.items() if k in permitted}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fail(code: str, base: dict, *, ambiguous: bool = False) -> int:
    base = dict(base)
    base["status"] = "STOP_AMBIGUOUS_MAY_HAVE_SUBMITTED" if ambiguous else "STOP_BEFORE_SUBMISSION"
    base["reason_code"] = code
    base["timestamp_utc"] = iso_now()
    save_public_record(base)
    print("LIVE_FREE STOP:", code)
    return 1


def _dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            v = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(v)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def question_deadline(q):
    for name in ("scheduled_close_time", "close_time", "forecasting_close_time"):
        value = _dt(getattr(q, name, None))
        if value is not None:
            return value
    return None


def check_question(q) -> bool:
    try:
        from forecasting_tools.data_models.questions import BinaryQuestion, QuestionState
        u = urlsplit(q.page_url)
        if not (
            isinstance(q, BinaryQuestion)
            and q.state == QuestionState.OPEN
            and q.already_forecasted is False
            and u.scheme == "https"
            and u.hostname in ("www.metaculus.com", "metaculus.com")
            and isinstance(q.id_of_post, int)
            and isinstance(getattr(q, "id_of_question", None), int)
        ):
            return False
        deadline = question_deadline(q)
        if deadline is not None and deadline <= now_utc() + timedelta(minutes=MIN_REMAINING_MINUTES):
            return False
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def readback_selected_question(client, selected_question) -> bool:
    question_id = getattr(selected_question, "id_of_question", None)
    if not isinstance(question_id, int):
        raise ValueError("Selected question has no integer question ID")
    refreshed = client.get_question_by_post_id(
        selected_question.id_of_post, group_question_mode="unpack_subquestions"
    )
    questions = refreshed if isinstance(refreshed, list) else [refreshed]
    matches = [q for q in questions if getattr(q, "id_of_question", None) == question_id]
    if len(matches) != 1:
        raise ValueError("Could not uniquely read back selected question")
    return getattr(matches[0], "already_forecasted", None) is True


def github_runs_today() -> int:
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    workflow = os.getenv("GITHUB_WORKFLOW_REF", "")
    if not token or not repo:
        return -1
    m = re.search(r"\.github/workflows/([^@]+)@", workflow)
    wf = m.group(1) if m else "run_live_free.yaml"
    try:
        import requests
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            params={"per_page": 100, "created": now_utc().date().isoformat()},
            timeout=20,
        )
        if r.status_code != 200:
            return -1
        runs = r.json().get("workflow_runs", [])
        today = now_utc().date()
        return sum(
            1 for x in runs
            if _dt(x.get("created_at")) and _dt(x.get("created_at")).date() == today
        )
    except Exception:
        return -1


def openrouter_key_status() -> dict:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return {"ok": False, "reason": "MISSING_OPENROUTER_API_KEY"}
    try:
        import requests
        r = requests.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
        if r.status_code != 200:
            return {"ok": False, "reason": f"OPENROUTER_KEY_HTTP_{r.status_code}"}
        data = r.json().get("data", {})
        rate = data.get("rate_limit") or {}
        return {
            "ok": True,
            "is_free_tier": data.get("is_free_tier"),
            "usage_daily_usd": data.get("usage_daily"),
            "limit_remaining_usd": data.get("limit_remaining"),
            "rate_limit_requests": rate.get("requests"),
        }
    except Exception as e:
        return {"ok": False, "reason": "OPENROUTER_KEY_CHECK_" + type(e).__name__}


async def submit_once(question, client):
    from main import FallTemplateBot2026
    from forecasting_tools import GeneralLlm, PredictionExtractor, ReasonedPrediction

    def free_llm():
        return GeneralLlm(
            model=SDK_MODEL_NAME,
            temperature=0.2,
            timeout=70,
            allowed_tries=1,
        )

    class OneCallBinaryBot(FallTemplateBot2026):
        async def run_research(self, question):
            # External research is a separate deterministic tool layer:
            # search -> fetch -> extract/store -> local retrieval. The LLM only judges the evidence.
            import sys
            from pathlib import Path
            stack_src = Path(__file__).resolve().parent / "web_research_stack" / "src"
            if str(stack_src) not in sys.path:
                sys.path.insert(0, str(stack_src))
            try:
                from forecast_adapter import research_for_question
                return await asyncio.to_thread(research_for_question, question)
            except Exception as e:
                # Research outage must not prevent a forecast. Never fabricate missing web evidence.
                return (
                    "External research was unavailable (" + type(e).__name__ + "). "
                    "Do not invent web evidence; forecast from the question text, background, "
                    "resolution criteria, and general knowledge."
                )

        async def _binary_prompt_to_forecast(self, question, prompt):
            reasoning = await self.get_llm("default", "llm").invoke(prompt)
            prediction = PredictionExtractor.extract_last_percentage_value(
                reasoning,
                max_prediction=0.99,
                min_prediction=0.01,
            )
            if not isinstance(prediction, (int, float)) or not (
                0.01 <= float(prediction) <= 0.99
            ):
                raise ValueError("INVALID_BINARY_PROBABILITY")
            return ReasonedPrediction(
                prediction_value=float(prediction),
                reasoning=reasoning,
            )

    bot = OneCallBinaryBot(
        research_reports_per_question=1,
        predictions_per_research_report=1,
        enable_summarize_research=False,
        use_research_summary_to_forecast=False,
        publish_reports_to_metaculus=True,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=True,
        extra_metadata_in_explanation=False,
        required_successful_predictions=1.0,
        llms={
            role: free_llm()
            for role in ("default", "summarizer", "researcher", "parser")
        },
        metaculus_client=client,
    )
    roles = bot.make_llm_dict()
    if not all(
        SDK_MODEL_NAME in str(roles.get(role))
        for role in ("default", "summarizer", "researcher", "parser")
    ):
        raise RuntimeError("MODEL_ALLOWLIST_GUARD_FAILED")
    return await bot.forecast_question(question, return_exceptions=False)


def main() -> int:
    base = {
        "stage": "LIVE_FREE_V1",
        "timestamp_utc": iso_now(),
        "model_routing_id": ALLOWED_MODEL,
        "github_run_url": (
            f"https://github.com/{os.getenv('GITHUB_REPOSITORY', 'Ting-YiLin/metac-bot-template')}"
            f"/actions/runs/{os.getenv('GITHUB_RUN_ID', 'UNKNOWN')}"
        ),
        "github_sha": os.getenv("GITHUB_SHA", "UNKNOWN"),
        "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "UNKNOWN"),
        "submission_function_returned": False,
        "platform_readback_already_forecasted": False,
        "estimated_model_calls_this_run": 0,
        "max_daily_runs": MAX_RUNS_PER_UTC_DAY,
    }

    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("LIVE_FREE_MODE") != "1":
        return fail("GITHUB_ACTIONS_LIVE_GATE_MISSING", base)
    if os.getenv("GITHUB_REPOSITORY") != "Ting-YiLin/metac-bot-template":
        return fail("REPOSITORY_NOT_ALLOWLISTED", base)
    if os.getenv("GITHUB_RUN_ATTEMPT") != "1":
        return fail("RERUN_BLOCKED_CHECK_EXISTING_RECEIPT", base)
    if os.getenv("LIVE_FREE_MODEL") != ALLOWED_MODEL:
        return fail("MODEL_NOT_FREE_ROUTER", base)
    if not os.getenv("METACULUS_TOKEN") or not os.getenv("OPENROUTER_API_KEY"):
        return fail("NEED_USER_AUTH", base)
    for name in PROHIBITED_PROVIDER_ENVS:
        if os.getenv(name):
            return fail("UNAPPROVED_PROVIDER_KEY_PRESENT_" + name, base)

    daily = github_runs_today()
    base["daily_run_count"] = daily
    if daily < 0:
        return fail("DAILY_RUN_COUNT_UNVERIFIED", base)
    if daily > MAX_RUNS_PER_UTC_DAY:
        return fail("DAILY_RUN_CAP_REACHED", base)

    key_status = openrouter_key_status()
    base["openrouter_key_valid"] = bool(key_status.get("ok"))
    if not key_status.get("ok"):
        return fail(
            str(key_status.get("reason", "OPENROUTER_KEY_INVALID")),
            base,
        )
    base["openrouter_is_free_tier"] = key_status.get("is_free_tier")
    base["openrouter_usage_daily_usd"] = key_status.get("usage_daily_usd")
    base["openrouter_limit_remaining_usd"] = key_status.get("limit_remaining_usd")
    base["openrouter_rate_limit_requests"] = key_status.get("rate_limit_requests")
    if (
        isinstance(base["openrouter_limit_remaining_usd"], (int, float))
        and base["openrouter_limit_remaining_usd"] < 0
    ):
        return fail("OPENROUTER_NEGATIVE_BALANCE", base)

    try:
        from forecasting_tools import MetaculusClient
        client = MetaculusClient()
        candidates = []
        for tournament in ALLOWED_TOURNAMENTS:
            questions = client.get_all_open_questions_from_tournament(tournament)
            for q in questions:
                if check_question(q):
                    deadline = question_deadline(q)
                    candidates.append(
                        (
                            deadline or datetime.max.replace(tzinfo=timezone.utc),
                            tournament,
                            q,
                        )
                    )
    except Exception as e:
        return fail("FETCH_FAILED_" + type(e).__name__, base)

    candidates.sort(
        key=lambda x: (x[0], x[2].id_of_post, x[2].id_of_question)
    )
    base["eligible_count"] = len(candidates)
    if not candidates:
        base["status"] = "NO_ELIGIBLE_NEW_BINARY_QUESTION"
        base["reason_code"] = "NO_OP"
        save_public_record(base)
        print("LIVE_FREE no eligible unforecasted binary question; no model call.")
        return 0

    deadline, tournament, q = candidates[0]
    base.update(
        {
            "tournament": tournament,
            "question_post_id": q.id_of_post,
            "question_id": q.id_of_question,
            "question_url": q.page_url,
            "selected_reason": "earliest_close_then_id",
            "scheduled_close_time": (
                None if deadline.year == datetime.max.year else deadline.isoformat()
            ),
            "minutes_to_close": (
                None
                if deadline.year == datetime.max.year
                else round((deadline - now_utc()).total_seconds() / 60, 1)
            ),
        }
    )

    base["estimated_model_calls_this_run"] = 1
    try:
        report = asyncio.run(submit_once(q, client))
        base["submission_function_returned"] = True
        base["report_type"] = type(report).__name__
    except Exception as e:
        return fail(
            "SUBMIT_AMBIGUOUS_CHECK_PLATFORM_" + type(e).__name__,
            base,
            ambiguous=True,
        )

    try:
        base["platform_readback_already_forecasted"] = readback_selected_question(
            client, q
        )
    except Exception as e:
        base["platform_readback_error_type"] = type(e).__name__

    base["timestamp_utc"] = iso_now()
    if base["platform_readback_already_forecasted"]:
        base["status"] = "PASS_RECEIPT_READBACK"
        base["reason_code"] = "SUBMITTED_ONCE"
        save_public_record(base)
        print("LIVE_FREE PASS receipt/readback:", base["question_url"])
        return 0

    base["status"] = "PENDING_PLATFORM_ACCOUNT_CONFIRMATION"
    base["reason_code"] = "READBACK_NOT_CONFIRMED_DO_NOT_RETRY"
    save_public_record(base)
    print("LIVE_FREE submission returned but readback unconfirmed; do not retry.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
