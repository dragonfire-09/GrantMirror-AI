"""
Scoring model: produces criterion-level scores with confidence intervals.
Currently rule-based; designed to be replaced with ML model when training data available.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config import ActionType, ACTION_TYPE_CONFIGS, SCORE_DESCRIPTORS_0_5


@dataclass
class ScoreResult:
    criterion: str
    score: float
    confidence_low: float
    confidence_high: float
    descriptor: str
    threshold: float
    threshold_met: bool
    margin: float  # Distance from threshold


@dataclass
class AggregateScore:
    criterion_scores: List[ScoreResult]
    total_weighted: float
    total_max: float
    total_threshold: float
    total_threshold_met: bool
    all_criteria_met: bool
    funding_band: str  # "funded", "reserve_list", "below_threshold", "well_below"
    risk_assessment: str


def get_score_descriptor(score: float) -> str:
    """Get official EC descriptor for a score."""
    # Round to nearest 0.5
    rounded = round(score * 2) / 2
    base = int(rounded)

    if base in SCORE_DESCRIPTORS_0_5:
        desc = SCORE_DESCRIPTORS_0_5[base]
        if rounded != base:
            next_desc = SCORE_DESCRIPTORS_0_5.get(base + 1, "")
            return f"Between: {desc} / {next_desc}"
        return desc

    return "Score outside expected range"


def calculate_confidence_interval(
    score: float,
    num_weaknesses: int,
    num_strengths: int,
    has_missing_elements: bool,
) -> Tuple[float, float]:
    """
    Calculate confidence interval for a score.
    Based on the insight that real evaluators can differ by ±0.5-1.0 points.
    """
    # Base uncertainty
    base_uncertainty = 0.5

    # More weaknesses = more downside risk
    if num_weaknesses > 3:
        base_uncertainty += 0.25

    # Missing elements increase uncertainty
    if has_missing_elements:
        base_uncertainty += 0.25

    # Near threshold = higher uncertainty
    if 2.5 <= score <= 3.5:
        base_uncertainty += 0.25

    conf_low = max(0.0, score - base_uncertainty)
    conf_high = min(5.0, score + base_uncertainty)

    return round(conf_low, 1), round(conf_high, 1)


def determine_funding_band(
    total_weighted: float,
    total_threshold: float,
    total_max: float,
    all_criteria_met: bool,
) -> str:
    """
    Determine funding probability band.
    Note: actual funding depends on competition, budget, and portfolio considerations.
    """
    if not all_criteria_met:
        return "below_threshold"

    if total_weighted < total_threshold:
        return "below_threshold"

    ratio = total_weighted / total_max
    margin = total_weighted - total_threshold

    if ratio >= 0.85:
        return "funded"
    elif ratio >= 0.75:
        return "reserve_list"
    elif margin > 0:
        return "below_threshold"
    else:
        return "well_below"


def aggregate_scores(
    criterion_scores: List[ScoreResult],
    action_type: ActionType,
) -> AggregateScore:
    """Aggregate criterion scores into overall assessment."""
    config = ACTION_TYPE_CONFIGS[action_type]

    total_weighted = 0.0
    for score_result, criterion_config in zip(criterion_scores, config.criteria):
        total_weighted += score_result.score * criterion_config.weight

    all_met = all(s.threshold_met for s in criterion_scores)
    total_met = total_weighted >= config.total_threshold and all_met

    band = determine_funding_band(
        total_weighted, config.total_threshold, config.total_max, all_met
    )

    # Risk assessment
    risks = []
    for s in criterion_scores:
        if s.margin < 0.5 and s.margin >= 0:
            risks.append(f"{s.criterion} is borderline ({s.score}, threshold {s.threshold})")
        elif s.margin < 0:
            risks.append(f"{s.criterion} below threshold ({s.score} < {s.threshold})")

    if total_weighted - config.total_threshold < 1.0 and total_met:
        risks.append(
            f"Total score ({total_weighted:.1f}) close to threshold ({config.total_threshold})"
        )

    risk_text = "; ".join(risks) if risks else "No critical threshold risks"

    return AggregateScore(
        criterion_scores=criterion_scores,
        total_weighted=round(total_weighted, 1),
        total_max=config.total_max,
        total_threshold=config.total_threshold,
        total_threshold_met=total_met,
        all_criteria_met=all_met,
        funding_band=band,
        risk_assessment=risk_text,
    )
