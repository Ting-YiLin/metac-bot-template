import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from evidence_quality import evidence_relevance

class TestEvidenceQuality(unittest.TestCase):
    def test_specific_sabarimala_evidence_passes(self):
        q='Will the Supreme Court of India reserve judgment in the 9-judge Sabarimala reference case by July 1, 2026?'
        t='Supreme Court 9-Judge Bench reserves judgment in the Sabarimala reference after hearings.'
        self.assertTrue(evidence_relevance(q,t)['accepted'])
    def test_generic_pacer_help_fails_musk_case(self):
        q='Will the Musk v. Altman trial Case No. 3:24-cv-04722 result in a jury verdict or settlement?'
        t='Jurors must consider evidence during a trial and render a verdict in the case.'
        r=evidence_relevance(q,t)
        self.assertFalse(r['accepted']);self.assertIn('missing_specific_entity_or_identifier',r['reason'])
    def test_specific_musk_docket_passes(self):
        q='Will the Musk v. Altman trial Case No. 3:24-cv-04722 result in a jury verdict or settlement?'
        t='Elon Musk v Samuel Altman, case 3:24-cv-04722. Complaint with jury demand; trial scheduling remains pending.'
        self.assertTrue(evidence_relevance(q,t)['accepted'])
    def test_generic_bulgaria_ministry_page_fails(self):
        q='Will Bulgaria have a regular non-caretaker government in office by June 1, 2026?'
        t='Bulgaria investment destination and crop production news from the ministry.'
        self.assertFalse(evidence_relevance(q,t)['accepted'])
    def test_excluded_country_is_fail_closed(self):
        q='Will any country (excluding China, Indonesia, and the DRC) announce a major export restriction on a critical mineral?'
        t='China announced new rare earth export restrictions and critical mineral controls.'
        r=evidence_relevance(q,t)
        self.assertFalse(r['accepted']);self.assertIn('excluded_entity_present_fail_closed',r['reason'])

if __name__=='__main__':unittest.main()
