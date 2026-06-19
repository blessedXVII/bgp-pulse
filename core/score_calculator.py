from dataclasses import dataclass


@dataclass
class Weights:
    """
    Веса метрик в формуле интегральной оценки канала S.
    Сумма весов должна равняться 1, чтобы итоговый S оставался в диапазоне [0, 1].
    """
    m1: float = 0.4
    m2: float = 0.2
    m3: float = 0.2
    m4: float = 0.2

def _validate_metric(name: str, value: float) -> None:
    """
    Проверяет, что значение метрики находится в допустимом диапазоне [0, 1].

    Args:
        name: имя метрики, используется в сообщении об ошибке.
        value: значение метрики для проверки.

    Raises:
        ValueError: если value выходит за пределы [0, 1].
    """
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0, 1], got {value}")

def calculate_score(m1: float, m2: float, m3: float, m4: float, weights: Weights) -> float:
    """
    Считает интегральную оценку состояния канала S.

    Формула: S = w1*m1 + w2*m2 + w3*m3 + w4*m4, где веса берутся из weights.

    Args:
        m1: загрузка канала, нормирована к [0, 1] (1 — лучшее).
        m2: задержка, нормирована к [0, 1] (1 — лучшее).
        m3: потери пакетов, нормированы к [0, 1] (1 — лучшее).
        m4: надёжность канала, нормирована к [0, 1] (1 — лучшее).
        weights: веса для каждой метрики.

    Returns:
        Итоговая оценка S в диапазоне [0, 1].

    Raises:
        ValueError: если любая из метрик вне диапазона [0, 1].
    """
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