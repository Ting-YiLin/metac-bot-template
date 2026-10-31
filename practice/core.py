"""Pure, off-line forecasting validation and routing. No network or publishing."""
from __future__ import annotations
import datetime as dt
import math
from statistics import median

LEVELS = ('GREEN', 'YELLOW_1', 'YELLOW_2', 'RED')
TYPES = ('binary', 'multiple_choice', 'numeric', 'date')
MODEL_IDS = {'lite': 'gemini-3.5-flash-lite', 'A': 'gemini-3.8-flash',
             'B': 'gemini-3.8-flash', 'C': 'gemini-3.8-flash',
             'check': 'gemini-3.6-flash'}

def finite(x):
    return isinstance(x, (int,float)) and not isinstance(x,bool) and math.isfinite(x)

def as_date(x):
    if not isinstance(x, str): raise ValueError('date string required')
    value=x.strip()
    try:return dt.date.fromisoformat(value[:10])
    except ValueError:pass
    for fmt in ('%m/%d/%Y %H:%M:%S','%m/%d/%Y'):
        try:return dt.datetime.strptime(value,fmt).date()
        except ValueError:pass
    raise ValueError('unsupported date string format') from None

def as_probability(x):
    if not finite(x) or not 0.001 <= x <= 0.999:
        raise ValueError('probability must be in [0.001, 0.999]')
    return float(x)

def validate_complexity(c, *, label):
    if not isinstance(c,dict) or c.get('level') not in LEVELS:
        raise ValueError(f'{label}: invalid complexity level')
    if not isinstance(c.get('reason'),str) or not c['reason'].strip():
        raise ValueError(f'{label}: missing reason')
    return {'level':c['level'],'reason':c['reason'][:1000]}

def validate_prediction(kind, prediction, question):
    if kind not in TYPES or not isinstance(prediction,dict):
        raise ValueError('unknown type / missing prediction')
    if kind=='binary':
        return {'probability': as_probability(prediction.get('probability'))}
    if kind=='multiple_choice':
        opts = question.get('options') or []
        p = prediction.get('probabilities')
        if not isinstance(opts,list) or len(opts)<2 or not isinstance(p,dict) or set(opts)!=set(p):
            raise ValueError('multiple choice option keys must exactly match question')
        probs={str(k):float(p[k]) for k in opts if finite(p[k]) and 0.0<=p[k]<=1.0}
        if len(probs)!=len(opts) or abs(sum(probs.values())-1)>0.025:
            raise ValueError('invalid multiple choice distribution')
        s=sum(probs.values())
        if s<=0:raise ValueError('zero distribution')
        return {'probabilities':{k: v/s for k,v in probs.items()}}
    if kind=='numeric':
        median_value=prediction.get('median')
        low=prediction.get('low_80');high=prediction.get('high_80')
        if not all(map(finite,[median_value,low,high])) or not low<=median_value<=high:
            raise ValueError('invalid numeric median or 80-percent interval')
        minv,maxv=question.get('lower_bound'),question.get('upper_bound')
        if minv is not None and finite(minv) and low < minv:
            raise ValueError('numeric below boundary')
        if maxv is not None and finite(maxv) and high > maxv:
            raise ValueError('numeric above boundary')
        return {'median':float(median_value),'low_80':float(low),'high_80':float(high)}
    fields=('median_date','low_80_date','high_80_date')
    low,m,high=[as_date(prediction.get(k)) for k in ('low_80_date','median_date','high_80_date')]
    if not low<=m<=high: raise ValueError('invalid date interval')
    lo,hi=question.get('lower_bound'),question.get('upper_bound')
    if lo and low < as_date(lo):raise ValueError('date below bound')
    if hi and high > as_date(hi):raise ValueError('date above bound')
    return {k:prediction[k][:10] for k in fields}

def validate_primary(reply,question):
    if not isinstance(reply,dict):raise ValueError('primary response must be JSON object')
    # The single model response must contain pre, prediction, post in this order;
    # this does NOT establish a physically independent pre-answer lock.
    for key in ('pre_complexity','prediction','post_complexity','reasoning'):
        if key not in reply:raise ValueError('missing '+key)
    if not isinstance(reply['reasoning'],str) or not reply['reasoning'].strip():
        raise ValueError('missing reasoning')
    return {'pre_complexity':validate_complexity(reply['pre_complexity'],label='pre'),
            'prediction':validate_prediction(question['type'],reply['prediction'],question),
            'post_complexity':validate_complexity(reply['post_complexity'],label='post'),
            'reasoning':reply['reasoning'][:2200]}

def validate_third(reply,question):
    if not isinstance(reply,dict):raise ValueError('third response must be JSON object')
    return {'prediction':validate_prediction(question['type'],reply.get('prediction'),question),
            'post_complexity':validate_complexity(reply.get('post_complexity'),label='third post'),
            'reasoning':str(reply.get('reasoning',''))[:2200]}

def compare_forecasts(question, a, b, gap=0.20):
    kind=question['type']; pa=a['prediction'];pb=b['prediction']
    if kind=='binary':
        x=pa['probability'];y=pb['probability'];delta=abs(x-y)
        if (x<.5<=y) or (y<.5<=x):return {'route':'C','reason':'BINARY_DIRECTION_OPPOSITE','gap':round(delta,6)}
        if delta>=gap:return {'route':'C','reason':'BINARY_GAP','gap':round(delta,6)}
        return {'route':'check','reason':'BINARY_AGREE','gap':round(delta,6)}
    if kind=='multiple_choice':
        x=pa['probabilities'];y=pb['probabilities']
        ax=max(x,key=lambda k:x[k]);by=max(y,key=lambda k:y[k])
        tv=.5*sum(abs(x[k]-y[k]) for k in x)
        if ax!=by:return {'route':'C','reason':'DIFFERENT_TOP_OPTION','gap':round(tv,6)}
        return {'route':'C' if tv>=gap else 'check','reason':'MULTICHOICE_GAP' if tv>=gap else 'MULTICHOICE_AGREE','gap':round(tv,6)}
    if kind=='numeric':
        x,y=pa,pb
        nonoverlap=x['high_80']<y['low_80'] or y['high_80']<x['low_80']
        overall_span=max(x['high_80'],y['high_80'])-min(x['low_80'],y['low_80'])
        lower=question.get('lower_bound');upper=question.get('upper_bound')
        scale=upper-lower if finite(lower) and finite(upper) and upper>lower else max(overall_span,abs(x['median']),abs(y['median']),1.0)
        delta=abs(x['median']-y['median'])/scale
        return {'route':'C' if nonoverlap or delta>=gap else 'check',
                'reason':'NUMERIC_INTERVAL_DISJOINT' if nonoverlap else ('NUMERIC_GAP' if delta>=gap else 'NUMERIC_AGREE'),
                'gap':round(delta,6)}
    x,y=pa,pb
    dtv=lambda z:as_date(z).toordinal()
    nonoverlap=dtv(x['high_80_date'])<dtv(y['low_80_date']) or dtv(y['high_80_date'])<dtv(x['low_80_date'])
    span=max(dtv(x['high_80_date']),dtv(y['high_80_date']))-min(dtv(x['low_80_date']),dtv(y['low_80_date']))
    delta=abs(dtv(x['median_date'])-dtv(y['median_date']))
    threshold=max(30,0.2*max(span,1))
    return {'route':'C' if nonoverlap or delta>=threshold else 'check',
            'reason':'DATE_INTERVAL_DISJOINT' if nonoverlap else ('DATE_GAP' if delta>=threshold else 'DATE_AGREE'),
            'gap_days':delta,'threshold_days':threshold}

def aggregate(question,replies):
    if len(replies) not in (2,3): raise ValueError('require 2 or 3 valid replies')
    kind=question['type'];p=[x['prediction'] for x in replies]
    if kind=='binary': return {'probability':float(median(x['probability'] for x in p))}
    if kind=='multiple_choice':
        options=question['options'];m={k:median(x['probabilities'][k] for x in p) for k in options}
        total=sum(m.values())
        return {'probabilities':{k:float(v/total) for k,v in m.items()}}
    if kind=='numeric':
        return {k:float(median(x[k] for x in p)) for k in ('median','low_80','high_80')}
    agg={}
    for k in ('median_date','low_80_date','high_80_date'):
        day=round(median(as_date(x[k]).toordinal() for x in p))
        agg[k]=dt.date.fromordinal(day).isoformat()
    return agg

def complexity_summary(primary_a,primary_b,third=None):
    def detail(label,r):
        a=r.get('pre_complexity');b=r['post_complexity'];shift=None
        if a:shift=LEVELS.index(a['level'])-LEVELS.index(b['level'])
        return {'agent':label,'pre':a,'post':b,'pre_minus_post':shift}
    return [detail('A',primary_a),detail('B',primary_b)] + ([detail('THIRD',third)] if third is not None else [])
