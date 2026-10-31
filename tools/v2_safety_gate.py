"""Fail-closed safety gate for practice-only GitHub Actions workflow.
Run from fork root: python tools/v2_safety_gate.py --repo .
"""
from __future__ import annotations
import argparse,json,re
from pathlib import Path

PRODUCTION=('run_bot_on_tournament.yaml','run_bot_on_metaculus_cup.yaml')
KNOWN={'run_bot_on_tournament.yaml','run_bot_on_metaculus_cup.yaml','test_bot.yaml','review_bot.yaml','practice_five.yaml'}

def inspect(root):
    root=Path(root); errs=[]
    wd=root/'.github'/'workflows'
    files={p.name for p in wd.iterdir() if p.is_file() and p.suffix in ('.yml','.yaml')} if wd.exists() else set()
    if files!=KNOWN:errs.append('Unexpected workflow file set: '+','.join(sorted(files^KNOWN)))
    for name in PRODUCTION:
        path=wd/name
        if not path.exists():errs.append('missing '+name);continue
        s=path.read_text(encoding='utf-8')
        if re.search(r'(?m)^\s*(schedule|cron)\s*:',s) or re.search(r'(?m)^\s*-\s*cron\s*:',s):
            errs.append('PRODUCTION_SCHEDULE_EXISTS:'+name)
        if not re.search(r'(?m)^\s+if:\s*\$\{\{\s*false\s*\}\}\s*$',s):
            errs.append('PRODUCTION_JOB_ENABLED:'+name)
    p=wd/'practice_five.yaml'
    if not p.exists():errs.append('PRACTICE_WORKFLOW_MISSING')
    else:
        s=p.read_text(encoding='utf-8')
        if not re.search(r'(?m)^on:\s*\n\s{2}workflow_dispatch:\s*$',s):errs.append('PRACTICE_NOT_MANUAL_ONLY')
        for forbidden in ('schedule','push','pull_request','workflow_run','repository_dispatch'):
            if re.search(r'(?m)^\s*'+forbidden+r'\s*:',s):errs.append('AUTOMATIC_TRIGGER:'+forbidden)
        if 'uv run python -m practice.run --mode "$MODE"' not in s:errs.append('NOT_PRACTICE_ENTRY')
        if 'uv run python main.py' in s:errs.append('ORIGINAL_BOT_ENTRY')
        if s.count('uv run python -m practice.run --mode "$MODE"')!=1:errs.append('PRACTICE_ENTRY_COUNT_NOT_ONE')
        if 'permissions:\n  contents: read' not in s:errs.append('EXCESS_GITHUB_PERMISSIONS')
        if 'OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}' not in s:
            errs.append('FALLBACK_SECRET_NOT_GITHUB_SECRET')
        if 'V22_OPENROUTER_FREE_AUTHORIZED' not in s:
            errs.append('MISSING_FALLBACK_EXPLICIT_AUTH')
        if 'diagnostic' not in s or 'question_count' not in s:
            errs.append('MISSING_STAGED_RUN_CONTROLS')
        if 'timeout-minutes: 300' not in s:
            errs.append('MISSING_BOUNDED_WORKFLOW_TIMEOUT')
    scripts=[p for p in (root/'practice').rglob('*.py')]
    if len(scripts)<4:errs.append('PRACTICE_SOURCE_MISSING')
    for file in scripts:
        s=file.read_text(encoding='utf-8')
        for forbidden in ('publish_report_to_metaculus(','.forecast_on_tournament(','.post_forecast(',
                          'requests.post(', 'api/questions/forecast/', 'subprocess.run('):
            if forbidden in s: errs.append('PROHIBITED_SUBMISSION_OR_EXEC:'+file.name)
    router=root/'practice'/'router.py'
    if not router.is_file():errs.append('FREE_FALLBACK_SOURCE_MISSING')
    else:
        src=router.read_text(encoding='utf-8')
        if "ROUTER_MODEL = 'openrouter/free'" not in (root/'practice'/'gemini.py').read_text(encoding='utf-8'):
            errs.append('ROUTER_MODEL_NOT_STRICTLY_FREE')
        if 'openrouter/auto' in src or 'openrouter/auto' in (root/'practice'/'gemini.py').read_text(encoding='utf-8'):
            errs.append('PAID_AUTO_ROUTER_FORBIDDEN')
    s0=root/'tools'/'s0_safety_gate.py'
    if not s0.exists() or "'practice_five.yaml'" not in s0.read_text(encoding='utf-8'):
        errs.append('LEGACY_S0_GATE_NOT_UPDATED')
    return {'status':'PASS' if not errs else 'FAIL','problems':errs,'checked_workflows':sorted(files),
            'submission_enabled':False,'models_allowlisted':['gemini-3.5-flash-lite','gemini-3.8-flash','gemini-3.6-flash','openrouter/free']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',default='.')
    a=p.parse_args();r=inspect(Path(a.repo))
    path=Path(a.repo)/'v2_preflight.json'
    path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print('V2 safety gate:',r['status'])
    for e in r['problems']:print('ERROR:',e)
    return 0 if r['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
