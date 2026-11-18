"""Pure, auxiliary MiniBench scoring. NEVER represents official Spot Peer Score."""
from datetime import datetime,timezone
import math
CANCELED={'annulled','ambiguous','canceled','cancelled','not_enough_info','not_enough_information','not_resolved'}
OUTBOUND={'below_lower_bound','above_upper_bound','below_lower','above_upper'}
def timestamp(x):
    if isinstance(x,(int,float)) and not isinstance(x,bool):return datetime.fromtimestamp(x,tz=timezone.utc)
    if isinstance(x,str) and x:
        z=datetime.fromisoformat(x.replace('Z','+00:00'))
        if z.tzinfo is None:raise ValueError('TIMESTAMP_TIMEZONE_MISSING')
        return z.astimezone(timezone.utc)
    raise ValueError('HISTORY_TIMESTAMP_MISSING')
def norm_resolution(state,raw):
    state=str(state or '').lower().replace('_','')
    if raw is not None and str(raw).lower().strip() in CANCELED:return 'CANCELED',None
    if raw is not None and str(raw).lower().strip() in OUTBOUND:return 'OUT_OF_BOUNDS',None
    if state!='resolved':return 'PENDING_RESOLUTION',None
    if raw is None or raw=='':return 'RESOLUTION_MISSING',None
    if isinstance(raw,(str,bool,int,float)):return 'RESOLVED_VALID',raw
    return 'RESOLUTION_UNRECOGNIZED',None
def vector_valid(v,kind):
    if not isinstance(v,list) or not v or any(type(x) not in (int,float) or not math.isfinite(x) for x in v):return False
    if kind in ('BinaryQuestion','MultipleChoiceQuestion'):
        return len(v)>=2 and all(0<=x<=1 for x in v) and abs(sum(v)-1)<=.002
    if kind in ('NumericQuestion','DateQuestion','DiscreteQuestion'):
        return len(v)==201 and all(0<=x<=1 for x in v) and all(a<=b+1e-10 for a,b in zip(v,v[1:]))
    return False
def binary_metrics(v,y):
    if len(v)!=2 or not vector_valid(v,'BinaryQuestion') or y not in (0,1):raise ValueError('INVALID_BINARY')
    return {'binary_brier':(v[1]-y)**2,'binary_log_loss':-math.log(max(v[y],1e-15))}
def choice_metrics(v,winner):
    if not vector_valid(v,'MultipleChoiceQuestion') or type(winner)!=int or not 0<=winner<len(v):raise ValueError('INVALID_MULTICLASS')
    return {'multiclass_brier':sum((p-(i==winner))**2 for i,p in enumerate(v)), 'multiclass_log_loss':-math.log(max(v[winner],1e-15))}
def numeric_crps(v,truth,low,high):
    if not vector_valid(v,'NumericQuestion') or type(truth) not in (int,float) or not low<truth<high:raise ValueError('INVALID_LINEAR_CDF_OR_TRUTH')
    width=(high-low)/200;area=0.
    for i in range(200):
        a=low+i*width;b=a+width;p=v[i];q=v[i+1]
        def part(left,right,target):
            if right<=left:return 0.
            f=p+(q-p)*(left-a)/width-target
            g=p+(q-p)*(right-a)/width-target
            return (right-left)*(f*f+f*g+g*g)/3
        s=max(a,min(truth,b))
        area+=part(a,s,0)+part(s,b,1)
    return area
def choose_last_before_close(history,close):
    if not isinstance(history,list) or not history:return None,'HISTORY_NOT_AVAILABLE'
    try:cut=timestamp(close)
    except Exception:return None,'QUESTION_CLOSE_TIME_MISSING'
    options=[];unknown=0
    for f in history:
        if not isinstance(f,dict) or 'forecast_values' not in f:continue
        stamp=next((f[k] for k in ('start_time','created_at','created_time','timestamp','forecast_timestamp') if f.get(k) is not None),None)
        try:t=timestamp(stamp)
        except (ValueError,TypeError,OverflowError):unknown+=1;continue
        if t<=cut:options.append((t,f))
    if unknown:return None,'HISTORY_TIMESTAMP_MISSING'
    if not options:return None,'NO_VALID_PRECLOSE_FORECAST'
    options.sort(key=lambda z:z[0])
    return options[-1][1],None
def resolve_choice(raw,options):
    if not isinstance(options,list) or not all(isinstance(z,str) for z in options):raise ValueError('OPTIONS_MISSING')
    if not isinstance(raw,str) or raw not in options:raise ValueError('WINNER_NOT_MATCHED_EXACT_OPTION')
    return options.index(raw)
