# MiniBench settlement audit — independent READ-ONLY (2026-11-18)

## Scope and current verified observation
- Frozen live-origin commit: `1dbf44015fbba9979cf9ebe1fe2831c7dbc3dce6`.
- Only the `experiment/minibench-score-audit-20261118` branch is writable.
- Validated original confirmed submissions: 46870, 46869, 46871, 46877.
- First authenticated runner: [44239396078](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44239396078).
- Authenticated run [44239918982](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44239918982) found **four structurally valid in-memory historical forecast vectors**, pre-close timestamps, but **four closed, zero resolved** as of 2026-11-18 04:49 UTC.
- No real official Spot Peer Score available; never substitute own Brier or approximate CRPS.
- Subsequent runs also dynamically read existing public *redacted* submission receipts on the separate state branch, and do not treat those receipts as forecast values.

## How the audit works
`.github/workflows/experimental_minibench_audit_readonly.yml` only runs `experimental_minibench_audit/collector.py` with HTTP GET and read-only GitHub access. It performs offline regression tests and fails if an HTTP mutation call is present. Only redacted CSV and JSON are uploaded to Actions artifacts. Probability vectors, individual rationales, and tokens stay in runner memory.

All five formats have guarded parsing/scoring code paths: BinaryQuestion, MultipleChoiceQuestion, NumericQuestion, DateQuestion, DiscreteQuestion. For continuous types only *verified linear scale* 201-point CDFs support a clearly labeled **research auxiliary CRPS approximation**, not platform scoring. Other scales, no history timestamps, invalid options, canceled and out-of-bounds resolutions remain unscored.

## Recurrence caveat
GitHub `schedule` does **not** execute workflows that exist only on non-default branches. To preserve `main` and all live workflows, recurrence is instead triggered by a separate six-hour ChatGPT automation, which writes a timestamp-only JSON request under `experimental_minibench_audit/requests/` on this isolated branch. That push triggers the GET-only audit. Existing forecast and monitoring automations are unchanged.

## Process audit boundary
`historical_missed_audit.json` holds four observed 2026-11-17 late-open candidates (46873–46876) and elapsed minutes until close. Root cause is `INCOMPLETE_EVIDENCE` for each because the Work execution, encrypted file link, submission run, and readback cannot all be chained. It is not an all-question or ~60-question census.

No automated forecast is submitted, no encrypted queue is read/decrypted, and no changes are made to the live system or its submission workflow.
