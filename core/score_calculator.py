from dataclasses import dataclass


@dataclass
class Weights:
    m1: float = 0.4
    m2: float = 0.2
    m3: float = 0.2
    m4: float = 0.2

def _validate_metric(name: str, value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0, 1], got {value}")

def calculate_score(m1: float, m2: float, m3: float, m4: float, weights: Weights) -> float:
    _validate_metric("m1", m1)
    _validate_metric("m2", m2)
    _validate_metric("m3", m3)
    _validate_metric("m4", m4)

    score = (
        weights.m1 * m1
        + weights.m2 * m2
        + weights.m3 * m3
        + weights.m4 * m4
    )
    return score

if __name__ == "__main__":
    w = Weights()
    s = calculate_score(0.8, 0.9, 0.85, 0.95, w)
    print(s)