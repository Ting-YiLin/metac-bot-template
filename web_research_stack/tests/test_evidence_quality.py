import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from evidence_quality import evidence_relevance

class TestEvidenceQuality(unittest.TestCase):
    def test_specific_sabarimala_evidence_passes(self):
        q='Will the Supreme Court of India reserve judgment in the 9-judge Sabarimala reference case by July 1, 2026?'
        t='Supreme Court 9-Judge Bench reserves verdict in Sabarimala reference after hearings.'
        self.assertTrue(evidence_relevance(q,t)['accepted'])
    def test_generic_pacer_help_fails_musk_case(self):
        q='Will the Musk v. Altman trial Case No. 3:24-cv-04722 result in a jury verdict or settlement?'
        t='PACER allows anyone with an account to search federal court case records and opinions.'
        self.assertFalse(evidence_relevance(q,t)['accepted'])
    def test_generic_bulgaria_ministry_page_fails(self):
        q='Will Bulgaria have a regular non-caretaker government in office by June 1, 2026?'
        t='The Bulgarian economy ministry discussed investment and crop production.'
        self.assertFalse(evidence_relevance(q,t)['accepted'])

if __name__=='__main__':unittest.main()
