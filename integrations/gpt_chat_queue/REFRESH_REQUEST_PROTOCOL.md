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

## Immutable return channel and three-minute acceptance budget (v2)

**Do not use the mutable** `state/gpt_chat_candidate_feed.json` **as the primary
acknowledgement for a GPT request.** A scheduled backup refresh can overwrite it
after the requested update, and chat-level reads may show a stale copy.

Each valid on-demand `request_id` creates a separate, create-only JSON file:

`tingyi001-test-state:state/gpt_chat_refresh_results/{request_id}.json`

This file contains the normal candidate fields PLUS:
- `refresh_request_id` equals the request file name (without .json);
- `refresh_trigger=GPT_REQUEST`;
- `refresh_status=COMPLETE`;
- `refresh_run_id` and `refresh_completed_at_utc`.

GitHub Actions persists this immutable file **before** updating the legacy
shared candidate feed. The per-request file is never intentionally overwritten.
Missing result file means *pending or failed*, not an empty candidate list.

GPT read procedure:
1. Create a unique read-only request, save the exact ID.
2. Read **that ID's dedicated result path**, not the shared feed.
3. Verify the matching ID, success status, scope, timestamp and eligible-item
   consistency. If an eligible binary question exists, check real-time state.
4. When a dedicated result is not yet present, check the matching GitHub
   Actions run state. While the task runtime permits, continue polling about
   every 15–20 seconds, up to a **180-second overall budget** measured from
   request creation. Never busy-loop with multiple immediate read calls.
5. If the workflow finishes unsuccessfully, mark BLOCKED_REFRESH_ERROR.
   If 180 actual seconds have elapsed without the requested result, mark
   BLOCKED_REFRESH_TIMEOUT. If the chat task cannot remain active for 180
   seconds and must exit earlier, mark PENDING_REFRESH_UNCONFIRMED
   (not TIMEOUT), including the request ID so a future check can reconcile it.
6. Missing/new question = NO_ACTION only with a verified dedicated result and
   truly zero eligible questions. Never stop the recurring schedule.

**Important platform limitation:** ChatGPT scheduled turns do not provide a
guaranteed programmatic sleep or a guaranteed three-minute active runtime.
This is a target polling window, not a service-level guarantee. If strict
three-minute waiting is required, implement the wait and monitoring on the
GitHub side where wall-clock time and retries are deterministic.

The existing `gpt_chat_queue.yaml` still has `GPT_QUEUE_LIVE_SUBMIT: '0'`.
This request channel never submits a prediction.

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
