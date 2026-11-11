# ChatGPT scheduled research → GitHub queue → Metaculus testing area

## Status, 2026-11-11

Experimental pipeline, **binary test questions only**. Production competitions are disabled.
The new queue workflow sets `GPT_QUEUE_LIVE_SUBMIT=0` and **cannot submit**.
The original free testing bot and its hourly schedule remain unchanged.

## Technical sequence

1. An authorized ChatGPT scheduled task researches a question and writes one new
   JSON file in `integrations/gpt_chat_queue/pending/` on the `main` branch
   through the connected GitHub app.
2. The GitHub push starts `.github/workflows/gpt_chat_queue.yaml`.
3. The queue consumer validates schema, six market checks, three research
   stages, age (<=60 minutes), exact tournament and IDs.
4. The consumer checks the question is still open, in `bot-testing-area`,
   unforecasted by this account, binary, and not blocked after two failures.
5. Current mode: inspect and save a receipt, **no forecast POST**.
6. A later separately verified deployment may enable `TEST_SUBMIT` for unscored
   questions only. A returned POST is not treated as success until readback.

## Queue filename

`integrations/gpt_chat_queue/pending/q-{post_id}-{question_id}-{unique}.json`

Use a new filename for each independent run; no arbitrary paths, no secrets.
GitHub connector must create the file on **main**. JSON only. Do not edit
program files as part of the task.

## Required JSON object

```json
{
  "schema_version": 1,
  "source": "chatgpt_scheduled_research",
  "tournament": "bot-testing-area",
  "question_type": "BinaryQuestion",
  "post_id": 1234,
  "question_id": 5678,
  "p_yes": 0.62,
  "reasoning": "Concise substantive rationale explaining evidence and counterexamples.",
  "forecast_created_at_utc": "2026-11-11T05:40:00Z",
  "evidence_cutoff_utc": "2026-11-11T05:39:00Z",
  "research_rounds": {
    "broad": {
      "status": "DONE",
      "queries": ["Search terms"],
      "sources": [{"url": "https://example.org/primary"}]
    },
    "deep": {
      "status": "DONE",
      "queries": ["Counterexample and details"],
      "sources": []
    },
    "local_language": {
      "status": "DONE",
      "language": "fr",
      "queries": ["Requête dans la langue du pays concerné"],
      "sources": []
    }
  },
  "market_checks": {
    "polymarket": {"status": "NOT_FOUND", "url": null, "p_yes": null},
    "kalshi": {"status": "NOT_FOUND", "url": null, "p_yes": null},
    "manifold": {"status": "NOT_FOUND", "url": null, "p_yes": null},
    "metaculus": {"status": "NOT_FOUND", "url": null, "p_yes": null},
    "hypermind": {"status": "NOT_FOUND", "url": null, "p_yes": null},
    "betfair": {"status": "NOT_FOUND", "url": null, "p_yes": null}
  },
  "mode": "DRY_RUN"
}
```

Replace placeholder IDs, timestamps, rationale and sources with real evidence;
never write the placeholder example as a forecast.

Market status values:
- `VERIFIED_EXACT`: matching resolution rules/time, exact market probability
  and verifiable booking/snapshot URL; `p_yes` is in [0,1].
- `RULE_MISMATCH`: similar but materially different resolution conditions.
- `RELATED_ONLY`: adjacent question, not an equivalent market.
- `NOT_FOUND`: explicitly searched but no relevant market.
- `ACCESS_BLOCKED`: API, region, login or page restriction; do not guess values.

Do not mislabel a similar market as EXACT. Do not infer missing prices.
Cite the evidence used in each round.

## Current safety gates

- A read-only and no-new-forecast case is a normal outcome; don't invent a prediction.
- `GPT_QUEUE_LIVE_SUBMIT` is hardcoded 0 in the workflow until separately enabled.
- Even after activation, only a `TEST_SUBMIT` payload can submit to `bot-testing-area`.
- `BinaryQuestion` only; multi-choice/numeric require separate mapping and tests.
- Exactly matching post_id + question_id, question open, already_forecasted false.
- No more than one POST attempt for each file, check readback after POST.
- Hard stop on missing persistent failure ledger, duplicate/unknown readback.
- GPT-generated forecast age max 60 minutes; live question state checked again.
- Never place Metaculus tokens or OpenAI secrets in GitHub queue files.
- No formal tournament submission in any branch of this pipeline.

## Acceptance tests

A: offline unit tests PASS in GitHub Actions (eight tests).
B: a synthetic `DRY_RUN` JSON created in `pending/` starts a queue run,
   yields an artifact and makes zero submissions.
C: ChatGPT hourly task actually writes a NEW JSON through its GitHub app,
   not merely describes a file. Validate queued payload and GitHub run.
D: with an actual open, unforecasted *binary test-area* question, verify
   one live `TEST_SUBMIT` POST and account readback. Do not assert D before then.
E: repeat at least 2 hourly chat schedules without manual approval and verify no
   duplicate submissions before relying on unattended operations.

The user must check scheduled-task approval/connection prompts. The GitHub
queue consumer cannot grant these permissions for ChatGPT.
