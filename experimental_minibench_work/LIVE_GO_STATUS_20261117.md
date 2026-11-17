# MiniBench scoring GO — rollout receipt 2026-11-17

User gave explicit GO for autonomous MiniBench submission, with ongoing monitoring and iterative improvement.

## What is actually deployed

- Repository `Ting-YiLin/metac-bot-template`, branch `experiment/work-luna-sol-minibench-20261117`.
- Scoring workflow `.github/workflows/experimental_minibench_live.yml` has approval env `BTF3_MINIBENCH_LIVE_APPROVED=1`, but only on a new encrypted queue-file event.
- Encrypted queue `experimental_minibench_work/live_pending/sealed-<hex>.json`: X25519 public-key encryption; private key is domain-separated from `METACULUS_TOKEN`, available only in Actions Secrets. Public key stored `tingyi001-test-state:state/minibench_work_public_key.json`.
- Each new queued forecast, if any, triggers authenticated MiniBench OPEN/binary/unforecasted check, a single forecast POST, exact forecast-value GET readback, then private comment POST and GET readback. Unconfirmed POST is NEVER automatically retried.
- Raw probability / rationale are **not** posted to public GitHub; receipts redact both.
- `main` and `run_live_free.yaml` still unchanged. Existing `Ting-Yi001 GPT測試區研究` hourly schedule untouched.
- `experimental_minibench_work/WORK_LIVE_SCHEDULE_START.md` is the Work-mode procedure.

## Verified evidence

- Earlier Work independent Sol 6.1 High on test-area case #43327: C stage completed without scored posting.
- Scored question #46868 only went through PASS_DRY_RUN and was shown to user in open-state pilot; **excluded from future scored queue**.
- Encrypted channel tests: 5/5 passed, submission/readback tests 7/7 passed in [GitHub Actions 44057138377](https://github.com/Ting-YiLin/metac-bot-template/actions/runs/44057138377).
- Unsubmitted empty live run: `NO_NEW_ENCRYPTED_FORECAST`, `files_seen=0`, `forecast_confirmations=0`, `private_comment_confirmations=0`.
- Authenticated OPEN question slice and separate public-key publication verified; no credential was stored in GitHub public content.
- Offline global validation verified after fixing missing test dependencies.

## Scheduling limitation

- A separate hourly ChatGPT automation `MiniBench Luna／Sol 自動預測` is enabled through 2026-12-05. Its immediate `Run now` execution was delivered inline **to the current Chat conversation**, not a verifiably Work-capable agent with model-selected Sol 6.1 High. Therefore this immediate run must report `BLOCKED_MODEL_ROUTING` and produce **no live encrypted forecast**.
- A Work-created scheduled task using `WORK_LIVE_SCHEDULE_START.md` is still required for verified unattended Luna High → Sol High sub-agent execution. The current Chat-created automation cannot be described as having achieved that.
- The task should be created/configured directly inside Work, selecting the intended model there, and verified against at least one logged run.
- No scored prediction POST or private comment has yet occurred. First scored forecast and account participation-form eligibility have **not** been confirmed.

## Safety and competition policy

Official 2026 rules permit fully autonomous bots but prohibit human selection/tuning based on previews of open/upcoming tournament questions. Keep raw forecasts out of progress summaries and public source. Competition requires private rationale comments for all forecasted questions.

## Status labels

- `SCORING_PIPELINE_DEPLOYED`: YES
- `ENCRYPTED_QUEUE_READY`: YES
- `UNATTENDED_WORK_MODEL_ROUTING_PROVEN`: NO
- `FIRST_SCORED_FORECAST_CONFIRMED`: NO
- `PRIVATE_COMMENT_CONFIRMED`: NO
- `ACCOUNT_PRIZE_ELIGIBILITY_CHECKED`: NO

This is a deployment receipt, not a false claim of scored forecast success.
