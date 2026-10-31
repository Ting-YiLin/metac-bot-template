import unittest
from practice.fetch import select_five
from types import SimpleNamespace as S

class FetchTests(unittest.TestCase):
    def test_stratified_five(self):
        items=[]
        for i,t in enumerate(['binary','binary','multiple_choice','numeric','date','binary']):
            items.append(S(question_type=t,question_text='Question '+str(i),id_of_post=i+100,
                           id_of_question=i+200,page_url='https://www.metaculus.com/questions/'+str(i+100),
                           state='open',options=['A','B'] if t=='multiple_choice' else []))
        chosen,stats=select_five(items)
        self.assertEqual(len(chosen),5)
        self.assertEqual(stats['missing'],{k:0 for k in stats['missing']})
    def test_shortage_explicit(self):
        q=[{'id':'one','post_id':1,'question_id':1,'type':'binary'}]
        selected,stats=select_five(q)
        self.assertEqual(len(selected),1)
        self.assertEqual(stats['missing']['date'],1)

if __name__=='__main__':unittest.main()
