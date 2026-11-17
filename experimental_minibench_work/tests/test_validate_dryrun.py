import datetime as dt
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_dryrun import validate

NOW = dt.datetime(2026, 11, 17, 8, 0, tzinfo=dt.timezone.utc)

def fixture():
    return {
        'target': {'tournament_id': 'minibench', 'round_verified': True,
                   'question_id': 1024, 'post_id': 2048, 'question_type': 'BinaryQuestion',
                   'status': 'OPEN', 'already_forecasted': False, 'closes_at': '2026-11-17T11:00:00Z'},
        'forecast': {'question_id': 1024, 'p_yes': 0.43,
                     'reasoning': 'Independent analysis of requirements and primary sources.',
                     'sources': []},
        'control': {'mode': 'dry_run', 'submit_authorized': False, 'post_state': 'NONE'}
    }

class ContractTests(unittest.TestCase):
    def test_good_dry_run(self):
        self.assertEqual(validate(fixture(), NOW)['status'], 'DRY_RUN_VALID')
    def test_submit_block(self):
        r = fixture(); r['control']['mode'] = 'live'
        self.assertIn('MODE_MUST_BE_DRY_RUN', validate(r, NOW)['errors'])
    def test_wrong_competition(self):
        r = fixture(); r['target']['tournament_id'] = 'bot-testing-area'
        self.assertIn('TOURNAMENT_NOT_VERIFIED', validate(r, NOW)['errors'])
    def test_unknown_round(self):
        r = fixture(); r['target']['round_verified'] = False
        self.assertIn('ROUND_NOT_VERIFIED', validate(r, NOW)['errors'])
    def test_duplicate(self):
        r = fixture(); r['target']['already_forecasted'] = True
        self.assertIn('ALREADY_FORECASTED_OR_UNKNOWN', validate(r, NOW)['errors'])
    def test_post_unknown(self):
        r = fixture(); r['control']['post_state'] = 'POST_UNKNOWN'
        self.assertIn('POST_STATE_UNSAFE_OR_UNKNOWN', validate(r, NOW)['errors'])
    def test_deadline(self):
        r = fixture(); r['target']['closes_at'] = '2026-11-17T07:59:00Z'
        self.assertIn('DEADLINE_PASSED', validate(r, NOW)['errors'])
    def test_wrong_direction_or_range(self):
        r = fixture(); r['forecast']['p_yes'] = -0.2
        self.assertIn('INVALID_BINARY_PROBABILITY', validate(r, NOW)['errors'])
    def test_unknown_type(self):
        r = fixture(); r['target']['question_type'] = 'DateQuestion'
        self.assertIn('TYPE_NOT_YET_SUPPORTED', validate(r, NOW)['errors'])
    def test_reason(self):
        r = fixture(); r['forecast']['reasoning'] = ''
        self.assertIn('MISSING_INDEPENDENT_REASONING', validate(r, NOW)['errors'])
    def test_missing_timestamp(self):
        r = fixture(); r['target']['closes_at'] = None
        self.assertIn('INVALID_DEADLINE', validate(r, NOW)['errors'])

if __name__ == '__main__': unittest.main()
