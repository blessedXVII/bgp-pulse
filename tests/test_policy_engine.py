import pytest
from core.policy_engine import PolicyEngine, Thresholds, LocalPrefLevels


@pytest.fixture
def engine():
    thresholds = Thresholds()
    levels = LocalPrefLevels()
    return PolicyEngine(thresholds, levels)


def test_initial_state_is_fair(engine):
    assert engine.current_local_pref == 130


def test_rises_to_excellent(engine):
    result = engine.decide(0.9)
    assert result == 220


def test_hysteresis_prevents_flapping_near_good_threshold(engine):
    engine.decide(0.65)
    assert engine.current_local_pref == 180

    engine.decide(0.58)
    assert engine.current_local_pref == 180

    engine.decide(0.62)
    assert engine.current_local_pref == 180


def test_drops_below_hysteresis_gap(engine):
    engine.decide(0.65)
    assert engine.current_local_pref == 180

    engine.decide(0.50)
    assert engine.current_local_pref == 130


def test_full_drop_to_poor(engine):
    engine.decide(0.9)
    engine.decide(0.1)
    assert engine.current_local_pref == 80

def test_rises_from_good_to_excellent(engine):
    engine.decide(0.65)
    assert engine.current_local_pref == 180

    engine.decide(0.95)
    assert engine.current_local_pref == 220


def test_fair_state_stays_fair_within_gap(engine):
    engine.decide(0.5)
    assert engine.current_local_pref == 130


def test_fair_state_rises_to_good(engine):
    engine.decide(0.65)
    assert engine.current_local_pref == 180


def test_classify_directly_covers_all_branches():
    from core.policy_engine import Thresholds, LocalPrefLevels, PolicyEngine

    t = Thresholds()
    l = LocalPrefLevels()
    engine = PolicyEngine(t, l)

    assert engine._classify(0.9) == 220
    assert engine._classify(0.7) == 180
    assert engine._classify(0.5) == 130
    assert engine._classify(0.1) == 80

def test_fair_drops_to_poor(engine):
    engine.decide(0.3)
    assert engine.current_local_pref == 80


def test_poor_state_recovers_to_fair(engine):
    engine.decide(0.3)
    assert engine.current_local_pref == 80

    engine.decide(0.5)
    assert engine.current_local_pref == 130


def test_poor_state_recovers_directly_to_excellent(engine):
    engine.decide(0.3)
    assert engine.current_local_pref == 80

    engine.decide(0.9)
    assert engine.current_local_pref == 220