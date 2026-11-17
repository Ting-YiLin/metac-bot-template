"""MiniBench five-format adapter; delegates CDF construction to forecasting-tools.

Output is a Metaculus /api/questions/forecast/ payload and its expected
readback vector. Never guesses probabilities or changes a model's quantiles.
No model calls, secrets, or network operations in this module.
"""
from __future__ import annotations

import datetime as dt
import math

KINDS = {
    "BinaryQuestion": "binary",
    "MultipleChoiceQuestion": "multiple_choice",
    "NumericQuestion": "numeric",
    "DateQuestion": "date",
    "DiscreteQuestion": "discrete",
}
CONTINUOUS = {"NumericQuestion", "DateQuestion", "DiscreteQuestion"}


def canonical_type(question):
    return type(question).__name__


def forecast_format_skeleton(q):
    """Safe question constraints to give Sol, not the actual Sol forecast."""
    name = canonical_type(q)
    doc = {"question_type": name}
    if name == "MultipleChoiceQuestion":
        doc["options"] = list(q.options)
    if name in CONTINUOUS:
        doc.update({
            "lower_bound": q.lower_bound.isoformat() if name == "DateQuestion" else q.lower_bound,
            "upper_bound": q.upper_bound.isoformat() if name == "DateQuestion" else q.upper_bound,
            "open_lower_bound": q.open_lower_bound,
            "open_upper_bound": q.open_upper_bound,
            "zero_point": getattr(q, "zero_point", None),
            "cdf_size": q.cdf_size,
            "recommended_quantile_levels": [10,20,40,60,80,90],
        })
    return doc


def finite_probability(v):
    return type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1


def _numeric_cdf(q, data):
    from forecasting_tools.data_models.numeric_report import NumericDistribution, Percentile

    points = data.get("percentiles")
    if not isinstance(points,list) or len(points)<3:
        raise ValueError("PERCENTILES_REQUIRED")
    levels = []
    parsed = []
    for item in points:
        if not isinstance(item,dict) or set(item)!={"p","value"}:
            raise ValueError("INVALID_PERCENTILE_RECORD")
        p=item["p"]
        if not (type(p) in (int,float) and math.isfinite(p) and 0<p<1):
            raise ValueError("INVALID_PERCENTILE_PROBABILITY")
        if canonical_type(q)=="DateQuestion":
            if not isinstance(item["value"],str):
                raise ValueError("DATE_PERCENTILE_MUST_BE_ISO_STRING")
            t=dt.datetime.fromisoformat(item["value"].replace("Z","+00:00"))
            if t.tzinfo is None:
                raise ValueError("DATE_PERCENTILE_NEEDS_TIMEZONE")
            v=t.timestamp()
        else:
            v=item["value"]
            if not (type(v) in (int,float) and math.isfinite(v)):
                raise ValueError("INVALID_PERCENTILE_VALUE")
        levels.append(float(p))
        parsed.append((p,float(v)))
    if not all(a<b for a,b in zip(levels,levels[1:])):
        raise ValueError("PERCENTILE_LEVELS_NOT_INCREASING")
    if not all(a<=b for a,b in zip([v for _,v in parsed],[v for _,v in parsed][1:])):
        raise ValueError("QUANTILE_VALUES_NOT_MONOTONE")
    if not isinstance(q.cdf_size,int) or q.cdf_size<3 or q.cdf_size>1001:
        raise ValueError("CDF_SIZE_OUT_OF_RANGE")

    # Reuse standardized, bound-aware interpolation and platform granularity
    # from the competition template's official forecasting-tools dependency.
    dist=NumericDistribution.from_question(
        [Percentile(percentile=float(p),value=v) for p,v in parsed], q)
    cdf=[float(p.percentile) for p in dist.get_cdf()]
    _validate_cdf(cdf,q)
    return cdf


def _validate_cdf(cdf,q):
    if len(cdf)!=q.cdf_size or any(not finite_probability(v) for v in cdf):
        raise ValueError("INVALID_CDF_LENGTH_OR_VALUE")
    if any(right < left for left,right in zip(cdf,cdf[1:])):
        raise ValueError("CDF_NOT_MONOTONIC")
    if not q.open_lower_bound and abs(cdf[0])>1e-7:
        raise ValueError("CLOSED_LOWER_BOUND_VIOLATED")
    if not q.open_upper_bound and abs(cdf[-1]-1)>1e-7:
        raise ValueError("CLOSED_UPPER_BOUND_VIOLATED")
    if q.open_lower_bound and cdf[0]<0.001-1e-8:
        raise ValueError("OPEN_LOWER_TAIL_MISSING")
    if q.open_upper_bound and cdf[-1]>0.999+1e-8:
        raise ValueError("OPEN_UPPER_TAIL_MISSING")
    # Platform max per-inbound-bucket, scaled for discrete CDF sizes.
    max_step=min(1.0, 0.2 * (200 / (q.cdf_size-1)))
    if any((b-a)>max_step+1e-7 for a,b in zip(cdf,cdf[1:])):
        raise ValueError("CDF_BUCKET_TOO_CONCENTRATED")


def make_api_payload(data,q):
    name=canonical_type(q)
    if name not in KINDS:
        raise ValueError("UNSUPPORTED_QUESTION_TYPE:"+name)
    if data.get("question_type") != name:
        raise ValueError("QUESTION_TYPE_MISMATCH")

    if name=="BinaryQuestion":
        prob=data.get("p_yes")
        if not (finite_probability(prob) and 0.001 <= prob <= 0.999):
            raise ValueError("INVALID_BINARY_PROBABILITY")
        return {"probability_yes":float(prob)},[1-float(prob),float(prob)]

    if name=="MultipleChoiceQuestion":
        options=list(q.options)
        value=data.get("option_probabilities")
        if not isinstance(value,dict) or len(options)<2 or set(value)!=set(options):
            raise ValueError("OPTION_LABELS_DO_NOT_MATCH_QUESTION")
        vector=[value[option] for option in options]
        if not all(finite_probability(v) and v>=0.001 for v in vector):
            raise ValueError("INVALID_OPTION_PROBABILITY")
        if abs(sum(vector)-1)>0.00001:
            raise ValueError("MC_PROBABILITIES_DO_NOT_SUM_TO_ONE")
        normalized=[float(v)/sum(vector) for v in vector]
        return {"probability_yes_per_category":dict(zip(options,normalized))},normalized

    cdf=_numeric_cdf(q,data)
    return {"continuous_cdf":cdf},cdf


def forecast_contract(data):
    """Input-only check, deferred final compatibility to authoritative q."""
    name=data.get("question_type")
    if name not in KINDS:
        raise ValueError("UNSUPPORTED_TYPE")
    if name=="BinaryQuestion":
        if not (finite_probability(data.get("p_yes")) and 0.001<=data["p_yes"]<=0.999):
            raise ValueError("INVALID_P_YES")
    elif name=="MultipleChoiceQuestion":
        if not isinstance(data.get("option_probabilities"),dict):
            raise ValueError("MISSING_OPTION_PROBABILITIES")
    else:
        if not isinstance(data.get("percentiles"),list):
            raise ValueError("MISSING_PERCENTILES")
    return name
