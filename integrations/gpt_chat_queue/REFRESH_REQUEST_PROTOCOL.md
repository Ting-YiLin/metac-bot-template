# GPT-triggered Metaculus candidate refresh protocol (tested 2026-11-12 AEST)

This extends the existing **read-only testing-area candidate feed**. It is NOT
a forecast submission channel. The formal tournament remains disabled.

## Why

The hourly GitHub Actions schedule occasionally skips or delays triggers.
A scheduled ChatGPT task may then read a stale feed and incorrectly stop.
The solution is a causal, per-run handshake: GPT requests refresh, GitHub
publishes with a matching request ID, GPT only accepts that matching result.

## One GPT scheduled turn

1. Read accurate current UTC time, format `YYYYMMDDTHHMMSSZ`.
2. Select a unique lowercase 6–16-character suffix, e.g. `e4b2c9af`.
3. `request_id = req-YYYYMMDDTHHMMSSZ-e4b2c9af`.
4. GitHub connector **create_file** (new file, NOT update) on `main`:

   `integrations/gpt_chat_queue/refresh_requests/{request_id}.json`

5. Exact JSON payload:

```json
{
  "schema_version": 1,
  "request_id": "req-20261111T212922Z-a92c0d73",
  "source": "chatgpt_scheduled_research",
  "tournament": "bot-testing-area",
  "intent": "READ_ONLY_REFRESH",
  "created_at_utc": "2026-11-11T21:29:22.122Z"
}
```

   **This is an illustrative old ID. Never reuse it.** Use the current
   measured UTC clock and a fresh ID for every attempt.

6. The GitHub `.github/workflows/export_gpt_chat_candidates.yaml` job
   starts on a **push** touching the new request-file path.
7. The job validates scope, age <=30 minutes, timestamp consistency,
   schema and ID. It only fetches `bot-testing-area` questions, then
   writes `state/gpt_chat_candidate_feed.json` to the isolated
   `tingyi001-test-state` branch.
8. GPT reads that file via its connected GitHub app. Accept it ONLY if:
   - `refresh_request_id` EXACTLY equals this run's `request_id`;
   - `refresh_trigger` is `GPT_REQUEST`;
   - `refresh_run_id` is present;
   - `checked_at_utc` and `refresh_completed_at_utc` are recent;
   - `tournament` is `bot-testing-area`;
   - `eligible_unforecasted` and `items` agree.
   Use the separate GitHub job status, if available, to verify completion.
   Retry **read-only polling** a few times during this same scheduled turn;
   do not assume a fixed completion delay or infinite waiting.
9. If the job fails, times out, permissions are missing, or the ID never
   matches, conclude `BLOCKED_REFRESH` for **THIS RUN ONLY**. Never
   silently fall back to a stale/unmatched candidate feed, and NEVER
   pause, cancel or disable the hourly ChatGPT automation.
10. If verified but no eligible binary test questions: `NO_ACTION` for
    this run only. Otherwise complete the existing three evidence-search
    rounds, six prediction-market checks, and any required follow-up
    searches before considering a separate `DRY_RUN` forecast JSON.
11. For predicted answer writing, follow `README.md` and its existing
    validation gates. The **submission** workflow still has
    `GPT_QUEUE_LIVE_SUBMIT: '0'` (real submissions disabled).

## Change boundaries

The request cannot authorize submitting to Metaculus, running a model,
altering workflow rules, changing permissions, or targeting a scored
competition. The original scheduled feed refresh at minute 07 and the
existing free bot remain as backup. On-demand refreshes are serialized
with the scheduled refresh using GitHub Actions concurrency.

## Verified E2E (2026-11-11T21:29Z UTC)

- Request ID: `req-20261111T212922Z-a92c0d73`
- GitHub commit: `cb97bb4c825f8ab1d54b140acc79a8209b72b6b5`
- Actions run: `43103484271` (success).
- Output feed: identical `refresh_request_id`,
  `refresh_trigger=GPT_REQUEST`,
  `refresh_run_id=43103484271`.
- Source read: 10 open questions, 0 eligible unforecasted.
- Actual forecast submissions: 0.
- 14 offline tests passed in Actions run `43103336999`.

**Not yet proven:** ChatGPT hourly automation, without a human, can create
the request and wait for the matching feed under its delegated GitHub
connection. That requires at least one scheduled-turn acceptance test.
