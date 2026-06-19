from dataclasses import dataclass


@dataclass
class Thresholds:
    """
    Пороговые значения S для переключения между уровнями LOCAL_PREF.

    Гистерезис реализуется через hysteresis_gap: переход вниз происходит
    только когда S падает ниже (порог - gap), а не просто ниже порога.
    """
    excellent: float = 0.8
    good: float = 0.6
    fair: float = 0.4
    hysteresis_gap: float = 0.05


@dataclass
class LocalPrefLevels:
    """
    Значения BGP LOCAL_PREF, соответствующие каждому уровню качества канала.

    Чем выше LOCAL_PREF — тем предпочтительнее путь для маршрутизатора R4.
    """
    excellent: int = 220
    good: int = 180
    fair: int = 130
    poor: int = 80


class PolicyEngine:
    """
    Принимает решение об изменении LOCAL_PREF на основе текущей оценки S.

    Реализует state-машину с гистерезисом для предотвращения флаппинга
    на граничных значениях S.
    """
    def __init__(self, thresholds: Thresholds, levels: LocalPrefLevels):
        """
        Инициализирует движок с заданными порогами и уровнями LOCAL_PREF.

        Args:
            thresholds: пороговые значения для переключения уровней.
            levels: значения LOCAL_PREF для каждого уровня качества.
        """
        self.thresholds = thresholds
        self.levels = levels
        self.current_local_pref: int = levels.fair

    def decide(self, score: float) -> int:
        """
        Принимает решение об изменении LOCAL_PREF на основе текущего S.

        Учитывает текущее состояние и гистерезис — переход вниз происходит
        только при достаточном падении S, чтобы избежать флаппинга.

        Args:
            score: текущая интегральная оценка канала S в диапазоне [0, 1].

        Returns:
            Актуальное значение LOCAL_PREF после применения политики.
        """
        t = self.thresholds
        gap = t.hysteresis_gap

        if self.current_local_pref == self.levels.excellent:
            if score < t.excellent - gap:
                self.current_local_pref = self._classify(score)
        elif self.current_local_pref == self.levels.good:
            if score >= t.excellent:
                self.current_local_pref = self.levels.excellent
            elif score < t.good - gap:
                self.current_local_pref = self._classify(score)
        elif self.current_local_pref == self.levels.fair:
            if score >= t.excellent:
                self.current_local_pref = self.levels.excellent
            elif score >= t.good:
                self.current_local_pref = self.levels.good
            elif score < t.fair - gap:
                self.current_local_pref = self.levels.poor
        else:
            if score >= t.fair:
                self.current_local_pref = self._classify(score)

        return self.current_local_pref

    def _classify(self, score: float) -> int:
        """
        Определяет уровень LOCAL_PREF по значению S без учёта текущего состояния.

        Используется внутри decide() для прямого маппинга S → LOCAL_PREF
        при переходах вверх или первичной классификации.

        Args:
            score: интегральная оценка канала S в диапазоне [0, 1].

        Returns:
            Значение LOCAL_PREF, соответствующее переданному score.
        """
        t = self.thresholds
        l = self.levels
        if score >= t.excellent:
            return l.excellent
        elif score >= t.good:
            return l.good
        elif score >= t.fair:
            return l.fair
        else:
            return l.poor

if __name__ == "__main__":
    t = Thresholds()
    l = LocalPrefLevels()
    engine = PolicyEngine(t, l)

    print(engine.decide(0.65))
    print(engine.decide(0.58))
    print(engine.decide(0.62))
    print(engine.decide(0.58))