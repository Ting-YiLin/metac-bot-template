import tempfile,unittest
from pathlib import Path
from tools.v2_safety_gate import inspect

class SecurityTests(unittest.TestCase):
    def setup_repo(self,root):
        wd=root/'.github'/'workflows';wd.mkdir(parents=True)
        for name in ('run_bot_on_tournament.yaml','run_bot_on_metaculus_cup.yaml'):
            (wd/name).write_text('name: disabled\non:\n  workflow_dispatch:\njobs:\n  do_nothing:\n    if: ${{ false }}\n',encoding='utf-8')
        (wd/'test_bot.yaml').write_text('on:\n  workflow_dispatch:\n',encoding='utf-8')
        (wd/'review_bot.yaml').write_text('on:\n  workflow_dispatch:\n',encoding='utf-8')
        package=Path(__file__).resolve().parents[1]
        workflow = package/'workflows'/'practice_five.yaml'
        if not workflow.exists(): workflow = package/'.github'/'workflows'/'practice_five.yaml'
        (wd/'practice_five.yaml').write_text(workflow.read_text(encoding='utf-8'),encoding='utf-8')
        (root/'practice').mkdir()
        for f in (package/'practice').glob('*.py'):
            (root/'practice'/f.name).write_text(f.read_text(encoding='utf-8'),encoding='utf-8')
        (root/'tools').mkdir()
        (root/'tools'/'s0_safety_gate.py').write_text("KNOWN = set(TWO_DISABLED + ('test_bot.yaml', 'review_bot.yaml', 'practice_five.yaml'))")
        return wd
    def test_all_manual_disabled_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_repo(root)
            self.assertEqual(inspect(root)['status'],'PASS')
    def test_production_schedule_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);wd=self.setup_repo(root)
            with (wd/'run_bot_on_tournament.yaml').open('a') as f:f.write('schedule:\n  - cron: "*/5 * * * *"\n')
            self.assertEqual(inspect(root)['status'],'FAIL')
    def test_auto_practice_trigger_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);wd=self.setup_repo(root)
            with (wd/'practice_five.yaml').open('a') as f:f.write('push:\n  branches: [main]\n')
            self.assertEqual(inspect(root)['status'],'FAIL')
    def test_existing_s0_gate_missing_update_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.setup_repo(root)
            (root/'tools'/'s0_safety_gate.py').write_text('KNOWN = set([])')
            self.assertEqual(inspect(root)['status'],'FAIL')

if __name__=='__main__':unittest.main()
