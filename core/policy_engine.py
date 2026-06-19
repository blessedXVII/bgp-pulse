from dataclasses import dataclass


@dataclass
class Thresholds:
    excellent: float = 0.8
    good: float = 0.6
    fair: float = 0.4
    hysteresis_gap: float = 0.05


@dataclass
class LocalPrefLevels:
    excellent: int = 220
    good: int = 180
    fair: int = 130
    poor: int = 80


class PolicyEngine:
    def __init__(self, thresholds: Thresholds, levels: LocalPrefLevels):
        self.thresholds = thresholds
        self.levels = levels
        self.current_local_pref: int = levels.fair

    def decide(self, score: float) -> int:
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