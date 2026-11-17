"""MiniBench Work bridge: offline-only forecast intake validator.

This file does NOT fetch credentials or submit forecasts.
A PASS means structural eligibility for a dry-run, not competition admission.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
from pathlib import Path


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError('timestamp missing')
    t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('timestamp missing timezone')
    return t.astimezone(dt.timezone.utc)


def validate(record, now=None):
    errors = []
    now = now or dt.datetime.now(dt.timezone.utc)
    target = record.get('target', {})
    forecast = record.get('forecast', {})
    control = record.get('control', {})
    if control.get('mode') != 'dry_run':
        errors.append('MODE_MUST_BE_DRY_RUN')
    if control.get('submit_authorized') is not False:
        errors.append('SUBMISSION_NOT_AUTHORIZED')
    if control.get('post_state') not in ('NONE', 'CONFIRMED_NOT_POSTED'):
        errors.append('POST_STATE_UNSAFE_OR_UNKNOWN')
    if target.get('round_verified') is not True:
        errors.append('ROUND_NOT_VERIFIED')
    tournament = target.get('tournament_id')
    if not isinstance(tournament, str) or not tournament.strip() or tournament in ('bot-testing-area','VERIFY_LIVE','UNVERIFIED'):
        errors.append('TOURNAMENT_NOT_VERIFIED')
    if target.get('question_type') != 'BinaryQuestion':
        errors.append('TYPE_NOT_YET_SUPPORTED')
    if target.get('status') != 'OPEN':
        errors.append('QUESTION_NOT_OPEN')
    if target.get('already_forecasted') is not False:
        errors.append('ALREADY_FORECASTED_OR_UNKNOWN')
    qid = target.get('question_id')
    if qid is None or str(qid).strip() == '' or str(forecast.get('question_id')) != str(qid):
        errors.append('QUESTION_ID_MISMATCH')
    if target.get('post_id') is None:
        errors.append('POST_ID_MISSING')
    try:
        if parse_time(target.get('closes_at')) <= now:
            errors.append('DEADLINE_PASSED')
    except (TypeError, ValueError):
        errors.append('INVALID_DEADLINE')
    p = forecast.get('p_yes')
    if not (isinstance(p, (float, int)) and not isinstance(p, bool) and math.isfinite(p) and 0 <= p <= 1):
        errors.append('INVALID_BINARY_PROBABILITY')
    if not isinstance(forecast.get('reasoning'), str) or len(forecast['reasoning'].strip()) < 20:
        errors.append('MISSING_INDEPENDENT_REASONING')
    if not isinstance(forecast.get('sources'), list):
        errors.append('SOURCES_NOT_LIST')
    return {'status': 'DRY_RUN_VALID' if not errors else 'BLOCKED',
            'errors': errors, 'submission_performed': False, 'question_id': qid}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input_json')
    ap.add_argument('--output', default=None)
    args = ap.parse_args()
    record = json.loads(Path(args.input_json).read_text(encoding='utf-8'))
    result = validate(record)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + '\n', encoding='utf-8')
    print(payload)
    return 0 if result['status'] == 'DRY_RUN_VALID' else 2


if __name__ == '__main__':
    raise SystemExit(main())
