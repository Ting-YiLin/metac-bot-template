"""FutureEval free-production runner for Ting-Yi001.

Operational policy:
- Target only the unscored Metaculus Bot Testing Area (project 32977).
- Eligibility filter is intentionally minimal: OPEN and not already forecasted.
- No question-type filter: let forecasting-tools dispatch supported types.
- Free OpenRouter route only. Each LLM invocation may retry up to 3 attempts.
- Process questions continuously within the run time budget; one failed question does not stop the batch.
- External research is deterministic and free: search -> fetch -> extract/store -> retrieve.
  The LLM only judges the resulting evidence.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_TOURNAMENTS = ("bot-testing-area",)
ALLOWED_MODEL = "openrouter/free"
SDK_MODEL_NAME = "openrouter/openrouter/free"
OUTPUT = Path("live_free_receipt.json")
MAX_RUN_SECONDS = int(os.getenv("LIVE_FREE_MAX_RUN_SECONDS", "1200"))
MAX_TEST_QUESTIONS = max(1, min(4, int(os.getenv("BOT_TEST_MAX_QUESTIONS", "2"))))
MODEL_ALLOWED_TRIES = 3


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def _dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
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


def eligible_question(q) -> bool:
    """Only the two user-approved filters: still open and not yet forecasted."""
    try:
        from forecasting_tools.data_models.questions import QuestionState
        return q.state == QuestionState.OPEN and q.already_forecasted is False
    except Exception:
        return False


def question_sort_key(item):
    tournament, q = item
    deadline = question_deadline(q) or datetime.max.replace(tzinfo=timezone.utc)
    post_id = getattr(q, "id_of_post", 10**18)
    question_id = getattr(q, "id_of_question", 10**18)
    return (deadline, post_id if isinstance(post_id, int) else 10**18,
            question_id if isinstance(question_id, int) else 10**18, tournament)


def save_receipt(summary: dict) -> None:
    OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def readback_selected_question(client, selected_question):
    """Read-only confirmation. Failure never triggers a second submission."""
    post_id = getattr(selected_question, "id_of_post", None)
    if not isinstance(post_id, int):
        return None
    refreshed = client.get_question_by_post_id(
        post_id, group_question_mode="unpack_subquestions"
    )
    questions = refreshed if isinstance(refreshed, list) else [refreshed]
    question_id = getattr(selected_question, "id_of_question", None)
    if isinstance(question_id, int):
        matches = [
            q for q in questions
            if getattr(q, "id_of_question", None) == question_id
        ]
        if len(matches) == 1:
            return getattr(matches[0], "already_forecasted", None) is True
        return None
    if len(questions) == 1:
        return getattr(questions[0], "already_forecasted", None) is True
    return None


def looks_like_quota_or_rate_limit(exc: BaseException) -> bool:
    text = (type(exc).__name__ + " " + str(exc)).lower()
    needles = (
        "429", "rate limit", "rate_limit", "quota", "free-models-per-day",
        "free model", "insufficient credits", "too many requests",
    )
    return any(x in text for x in needles)


def build_bot(client):
    from main import FallTemplateBot2026
    from forecasting_tools import GeneralLlm, PredictionExtractor, ReasonedPrediction

    def free_llm():
        return GeneralLlm(
            model=SDK_MODEL_NAME,
            temperature=0.2,
            timeout=75,
            allowed_tries=MODEL_ALLOWED_TRIES,
        )

    class FreeWebResearchBot(FallTemplateBot2026):
        # Reduce extra parser sampling. Parser invocation itself still has up to 3 retries.
        _structure_output_validation_samples = 1

        async def run_research(self, question):
            stack_src = (
                Path(__file__).resolve().parent / "web_research_stack" / "src"
            )
            if str(stack_src) not in sys.path:
                sys.path.insert(0, str(stack_src))
            try:
                from forecast_adapter import research_for_question
                return await asyncio.to_thread(research_for_question, question)
            except Exception as e:
                print(
                    "RESEARCH_FALLBACK",
                    getattr(question, "page_url", ""),
                    type(e).__name__,
                )
                return (
                    "External research was unavailable. Do not invent web evidence. "
                    "Forecast from the question text, background, resolution criteria, "
                    "fine print, and general knowledge."
                )

        async def _binary_prompt_to_forecast(self, question, prompt):
            # Binary output can be parsed deterministically, saving a parser-model call.
            reasoning = await self.get_llm("default", "llm").invoke(prompt)
            prediction = PredictionExtractor.extract_last_percentage_value(
                reasoning, max_prediction=0.99, min_prediction=0.01
            )
            if not isinstance(prediction, (int, float)):
                raise ValueError("INVALID_BINARY_PROBABILITY")
            prediction = float(prediction)
            if not 0.01 <= prediction <= 0.99:
                raise ValueError("INVALID_BINARY_PROBABILITY")
            return ReasonedPrediction(
                prediction_value=prediction,
                reasoning=reasoning,
            )

    return FreeWebResearchBot(
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


async def process_question(bot, client, tournament, q):
    item = {
        "tournament": tournament,
        "question_post_id": getattr(q, "id_of_post", None),
        "question_id": getattr(q, "id_of_question", None),
        "question_url": getattr(q, "page_url", None),
        "question_type": type(q).__name__,
        "scheduled_close_time": (
            question_deadline(q).isoformat() if question_deadline(q) else None
        ),
        "started_at": iso_now(),
        "status": "STARTED",
        "model_allowed_tries_per_invocation": MODEL_ALLOWED_TRIES,
        "research_mode": "free_search_fulltext_evidence",
    }
    try:
        report = await bot.forecast_question(q, return_exceptions=False)
        item["submission_function_returned"] = True
        item["report_type"] = type(report).__name__
        try:
            item["platform_readback_already_forecasted"] = (
                readback_selected_question(client, q)
            )
        except Exception as e:
            item["platform_readback_already_forecasted"] = None
            item["readback_error_type"] = type(e).__name__
        item["status"] = (
            "PASS_RECEIPT_READBACK"
            if item.get("platform_readback_already_forecasted") is True
            else "SUBMISSION_RETURNED_READBACK_UNCONFIRMED"
        )
        return item, False
    except Exception as e:
        # Do not retry forecast_question() as a whole: an exception after publish
        # could otherwise duplicate a submission. LLM retries happen internally.
        item["submission_function_returned"] = False
        item["error_type"] = type(e).__name__
        item["error"] = str(e)[:600]
        try:
            rb = readback_selected_question(client, q)
        except Exception:
            rb = None
        item["platform_readback_already_forecasted"] = rb
        if rb is True:
            item["status"] = "PASS_READBACK_AFTER_EXCEPTION"
        else:
            item["status"] = "FAILED_QUESTION_CONTINUE"
        return item, looks_like_quota_or_rate_limit(e)
    finally:
        item["finished_at"] = iso_now()


async def run_batch():
    from forecasting_tools import MetaculusClient

    started = time.monotonic()
    client = MetaculusClient()
    candidates = []
    fetch_errors = []

    for tournament in ALLOWED_TOURNAMENTS:
        try:
            questions = client.get_all_open_questions_from_tournament(tournament)
            for q in questions:
                if eligible_question(q):
                    candidates.append((tournament, q))
        except Exception as e:
            fetch_errors.append({
                "tournament": tournament,
                "error_type": type(e).__name__,
                "error": str(e)[:400],
            })

    candidates.sort(key=question_sort_key)
    bot = build_bot(client)

    summary = {
        "stage": "BOT_TESTING_AREA_V1_WEB_RESEARCH",
        "competition_submission_enabled": False,
        "max_questions_this_run": MAX_TEST_QUESTIONS,
        "timestamp_utc": iso_now(),
        "model_routing_id": ALLOWED_MODEL,
        "model_allowed_tries_per_invocation": MODEL_ALLOWED_TRIES,
        "eligible_filter": ["OPEN", "NOT_ALREADY_FORECASTED"],
        "question_type_filter": "NONE",
        "selection_order": "EARLIEST_CLOSE_THEN_IDS",
        "eligible_count": len(candidates),
        "fetch_errors": fetch_errors,
        "processed": [],
        "github_run_url": (
            f"https://github.com/{os.getenv('GITHUB_REPOSITORY', 'Ting-YiLin/metac-bot-template')}"
            f"/actions/runs/{os.getenv('GITHUB_RUN_ID', 'UNKNOWN')}"
        ),
        "github_sha": os.getenv("GITHUB_SHA", "UNKNOWN"),
    }

    for tournament, q in candidates:
        if len(summary["processed"]) >= MAX_TEST_QUESTIONS:
            summary["stop_reason"] = "TEST_BATCH_QUESTION_LIMIT"
            break
        if time.monotonic() - started >= MAX_RUN_SECONDS:
            summary["stop_reason"] = "RUN_TIME_BUDGET"
            break

        item, quota_stop = await process_question(bot, client, tournament, q)
        summary["processed"].append(item)
        save_receipt(summary)

        if quota_stop:
            summary["stop_reason"] = "FREE_ROUTE_QUOTA_OR_RATE_LIMIT"
            break

    if "stop_reason" not in summary:
        summary["stop_reason"] = (
            "NO_ELIGIBLE_QUESTIONS" if not candidates else "CANDIDATES_EXHAUSTED"
        )

    summary["finished_at"] = iso_now()
    summary["success_count"] = sum(
        1 for x in summary["processed"] if x["status"].startswith("PASS")
    )
    summary["submission_returned_count"] = sum(
        1 for x in summary["processed"] if x.get("submission_function_returned")
    )
    summary["failure_count"] = sum(
        1 for x in summary["processed"]
        if x["status"] == "FAILED_QUESTION_CONTINUE"
    )
    save_receipt(summary)
    return summary


def main() -> int:
    # No extra quota/key/safety preflight. Missing credentials or exhausted free
    # quota fail naturally at the API call, as requested.
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("BOT_TEST_MODE") != "1":
        print("Bot testing area mode requires GitHub Actions and BOT_TEST_MODE=1.")
        return 2

    summary = asyncio.run(run_batch())
    print(json.dumps({
        "stage": summary["stage"],
        "eligible_count": summary["eligible_count"],
        "processed_count": len(summary["processed"]),
        "success_count": summary["success_count"],
        "failure_count": summary["failure_count"],
        "stop_reason": summary["stop_reason"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
