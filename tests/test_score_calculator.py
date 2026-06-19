import pytest
from core.score_calculator import calculate_score, Weights


def test_score_with_default_weights():
    weights = Weights()
    score = calculate_score(0.8, 0.9, 0.85, 0.95, weights)
    assert score == pytest.approx(0.86)


def test_score_all_zeros():
    weights = Weights()
    score = calculate_score(0, 0, 0, 0, weights)
    assert score == 0


def test_score_all_ones():
    weights = Weights()
    score = calculate_score(1, 1, 1, 1, weights)
    assert score == pytest.approx(1.0)


def test_score_m1_dominates_due_to_weight():
    weights = Weights()
    high_m1 = calculate_score(1, 0, 0, 0, weights)
    high_m2 = calculate_score(0, 1, 0, 0, weights)
    assert high_m1 > high_m2


def test_invalid_metric_raises_value_error():
    weights = Weights()
    with pytest.raises(ValueError):
        calculate_score(1.5, 0.5, 0.5, 0.5, weights)