"""Fail-closed preflight for one-question, no-schedule, free-route CI test."""
import argparse
import json
import re
import subprocess
from pathlib import Path

OWNER = 'Ting-YiLin/metac-bot-template'
TWO_DISABLED = (
    'run_bot_on_tournament.yaml',
    'run_bot_on_metaculus_cup.yaml',
)
KNOWN = set(TWO_DISABLED + ('test_bot.yaml', 'review_bot.yaml'))
ONE_TEST_ENTRY = 'uv run python s0_one_test.py'


def inspect(root: Path) -> dict:
    problems = []
    workflows = root / '.github' / 'workflows'
    if not workflows.is_dir():
        return {'status':'FAIL','problems':['workflow directory missing']}
    existing = {p.name for p in workflows.iterdir() if p.is_file() and p.suffix in ('.yaml', '.yml')}
    if existing != KNOWN:
        problems.append('workflow filename set changed; expected exactly the 4 reviewed workflows')
    for name in TWO_DISABLED:
        path=workflows/name
        if not path.exists():
            problems.append(name+': missing')
            continue
        s=path.read_text(encoding='utf-8')
        if re.search(r'(?m)^\s*schedule\s*:',s) or re.search(r'(?m)^\s*-\s*cron\s*:',s):
            problems.append(name+': has a schedule')
        if not re.search(r'(?m)^\s+if:\s*\$\{\{\s*false\s*\}\}\s*$', s):
            problems.append(name+': job not disabled')
    test = workflows / 'test_bot.yaml'
    s = test.read_text(encoding='utf-8') if test.exists() else ''
    if not re.search(r'(?m)^on:\s*\n\s{2}workflow_dispatch:\s*$',s):
        problems.append('test workflow must be manually dispatched only')
    if any(re.search(r'(?m)^\s*'+word+r'\s*:',s) for word in
           ('schedule','push','pull_request','workflow_run','repository_dispatch')):
        problems.append('test workflow contains automatic trigger')
    if s.count(ONE_TEST_ENTRY)!=1:
        problems.append('test workflow must invoke the one-test script exactly once')
    if re.search(r'(?m)^\s*run:\s*.*\bmain\.py\b',s) or re.search(r'(?m)^\s+uv run python main\.py\b',s):
        problems.append('test workflow invokes default multi-question entrypoint')
    if 'S0_FREE_MODEL: \'openrouter/free\'' not in s:
        problems.append('free model setting missing')
    if not (root/'s0_one_test.py').exists():
        problems.append('single-test script missing')
    else:
        src=(root/'s0_one_test.py').read_text(encoding='utf-8')
        for needle in ('ALLOWED_TOURNAMENT = "bot-testing-area"',
                       'ALLOWED_MODEL = "openrouter/free"',
                       'predictions_per_research_report=1',
                       'research_reports_per_question=1',
                       'forecast_question(question, return_exceptions=False)'):
            if needle not in src:
                problems.append('single-test safety invariant missing: '+needle)
    # review_bot is read-only and protected by its own existing opt-in switch.
    rev = workflows/'review_bot.yaml'
    if rev.exists() and 'REVIEW_BOT_ENABLED' not in rev.read_text(encoding='utf-8'):
        problems.append('review bot schedule must remain gated')
    return {'status':'PASS' if not problems else 'FAIL',
            'checked_workflows':sorted(existing), 'problems':problems,
            'only_manual_test':not problems,
            'live_workflows_disabled':not problems}


def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',default='.')
    a=p.parse_args()
    root=Path(a.repo).resolve()
    result=inspect(root)
    (root/'s0_preflight.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('S0 safety preflight:',result['status'])
    for msg in result['problems']:print('ERROR:',msg)
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':
    raise SystemExit(main())
