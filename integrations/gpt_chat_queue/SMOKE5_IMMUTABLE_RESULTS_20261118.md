# Ting-Yi001 — immutable refresh E2E 5-run acceptance, 2026-11-18

Scope: **only** Metaculus `bot-testing-area`, read-only candidate refresh;
never prediction submission, no scored competition changes.

## Change set

- `integrations/gpt_chat_queue/export_candidates.py`: writes create-only
  `state/gpt_chat_refresh_results/{request_id}.json` to the isolated
  `tingyi001-test-state` branch **before** updating the mutable shared feed.
- `integrations/gpt_chat_queue/REFRESH_REQUEST_PROTOCOL.md`: primary
  per-request return channel; bounded 180 s target polling window;
  report `PENDING_REFRESH_UNCONFIRMED` rather than false 180 s timeout
  if a chat task ends earlier.
- `tests/test_gpt_refresh_protocol.py`: four tests added for immutable
  creation, overwrite refusal, path restriction and mutable-feed compatibility.
- Existing scheduled GPT task instructions revised without changing its hourly
  schedule, turning it off, or allowing forecast submission.

## Controlled end-to-end checks

Each distinct request was added to the main branch using the already-connected
GitHub app, then confirmed by reading **its own** immutable result on
`tingyi001-test-state`. GitHub workflow status verified independently.

| # | Request suffix | Workflow run | Final result | Approx seconds from request second to returned file |
|---|---|---:|---|---:|
| 1 | `041627Z-probe01aa` | [44236185507](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44236185507) | PASS | 30.3 |
| 2 | `041824Z-probe02aa` | [44236410574](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44236410574) | PASS | 23.8 |
| 3 | `041914Z-probe03aa` | [44236507342](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44236507342) | PASS | 27.9 |
| 4 | `042004Z-probe04aa` | [44236603134](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44236603134) | PASS | 32.0 |
| 5 | `042052Z-probe05aa` | [44236698830](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44236698830) | PASS | 27.0 |

All 5 workflows completed with GitHub conclusion `success`; all 5 returned
`refresh_request_id` exactly matching the request, `refresh_run_id`
matching the workflow run, `refresh_trigger=GPT_REQUEST`,
`refresh_status=COMPLETE`, open question count 10, eligible question count 0
and `items=[]`. No forecasts generated or submitted.

Check artifact: [GPT queue offline validation](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44236074573)
had **9 existing queue tests + 10 refresh protocol tests = 19 passing**.

## Evidence-qualified conclusions

PASS: GitHub read-only trigger, per-request ID mapping, durable immutable
result path, schema validation and five sequential repeatability checks.

NOT YET PASS: five *autonomous scheduled chat* executions. The five tests
above were initiated by an interactive chat using GitHub, not five hourly
automation runs. Scheduled prompt was updated and must be observed in
future natural hourly runs, including a delayed workflow case.

NOT YET PASS: actual end-to-end prediction research, multi-market checks,
binary scoring, MiniBench, or scored submission/readback. Current testing
candidate source contains 10 open questions, all already forecasted.
`gpt_chat_queue.yaml` remains gated at `GPT_QUEUE_LIVE_SUBMIT: '0'`.

Limitation: ChatGPT scheduled runs cannot be guaranteed to remain active
for an exact three-minute wait; target interval 15–20 s, max 180 s while
runtime allows. Never treat an early exit as a completed three-minute timeout.
