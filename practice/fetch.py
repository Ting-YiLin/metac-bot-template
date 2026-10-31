"""Fetch only a tiny sample of open questions from official bot-testing-area.
Requires the existing official forecasting-tools package and authorized METACULUS_TOKEN.
Read-only. No historical bulk download or leaderboard submission.
"""
from __future__ import annotations
import json,datetime as dt
from pathlib import Path

TARGETS={'binary':2,'multiple_choice':1,'numeric':1,'date':1}
PROJECT='bot-testing-area'

def safe_value(x):
    if x is None or isinstance(x,(bool,int,float,str)):return x
    if isinstance(x,(dt.datetime,dt.date)):return x.isoformat()
    return str(x)

def normalize_question(q):
    # pydantic model attributes vary across official forecasting-tools revisions.
    t=str(getattr(q,'question_type','') or getattr(q,'get_question_type',lambda:'' )()).lower()
    aliases={'multiple-choice':'multiple_choice','multiple choice':'multiple_choice'}
    t=aliases.get(t,t)
    if t not in TARGETS:return None
    try:
        text=str(q.question_text);post=int(q.id_of_post);qid=int(q.id_of_question)
        if not text.strip():return None
    except (AttributeError,TypeError,ValueError):return None
    attrs={'id':f'POST{post}_Q{qid}','source':'Metaculus authorized API:bot-testing-area',
           'type':t,'text':text,'post_id':post,'question_id':qid,
           'url':str(getattr(q,'page_url',f'https://www.metaculus.com/questions/{post}/')),
           'resolution_criteria':safe_value(getattr(q,'resolution_criteria','')),
           'fine_print':safe_value(getattr(q,'fine_print','')),
           'background_info':safe_value(getattr(q,'background_info','')),
           'lower_bound':safe_value(getattr(q,'lower_bound',None)),
           'upper_bound':safe_value(getattr(q,'upper_bound',None)),
           'state':str(getattr(q,'state',''))}
    if t=='multiple_choice':
        opts=getattr(q,'options',[])
        if isinstance(opts,dict):opts=list(opts.keys())
        vals=[str(getattr(o,'name',o)) for o in opts]
        attrs['options']=vals
        if len(set(vals))<2:return None
    return attrs

def select_five(items):
    selected=[];counts={k:0 for k in TARGETS}; seen=set()
    # deterministic selection by question/post ID
    normalized=[q for q in (normalize_question(x) if not isinstance(x,dict) else x for x in items) if q]
    for q in sorted(normalized,key=lambda x:(int(x.get('post_id',0)),int(x.get('question_id',0)))):
        t=q.get('type');qid=q.get('question_id',q.get('id'))
        if t not in counts or counts[t]>=TARGETS[t] or qid in seen:continue
        counts[t]+=1;seen.add(qid);selected.append(q)
        if len(selected)==5:break
    return selected,{'target':TARGETS,'selected':counts,'missing':{k:TARGETS[k]-counts[k] for k in counts}}

def fetch_authorized():
    from forecasting_tools.helpers.metaculus_client import MetaculusClient
    client=MetaculusClient()
    questions=client.get_all_open_questions_from_tournament(PROJECT,group_question_mode='unpack_subquestions')
    return select_five(questions)
