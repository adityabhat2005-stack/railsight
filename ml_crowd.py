import numpy as np
from sklearn.ensemble import RandomForestClassifier

class CrowdPredictor:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=60, max_depth=6, random_state=42)
        self._train_synthetic_corridor_model()

    def _train_synthetic_corridor_model(self):
        # Features: [hour (0-23), day_of_week (0=Mon..6=Sun), category_id, distance_km]
        # Labels: 0 = Low (Available Seating), 1 = Medium (Moderate Standee), 2 = High (Heavy Rush)
        rng = np.random.default_rng(42)
        X, y = [], []

        for _ in range(1500):
            hour = int(rng.integers(0, 24))
            dow = int(rng.integers(0, 7))
            cat_id = int(rng.integers(1, 8))
            dist = float(rng.uniform(15, 240))

            # Realistic Malabar-Mangaluru commuter patterns
            is_weekday = dow < 5
            is_morning_peak = 6 <= hour <= 9
            is_evening_peak = 16 <= hour <= 20
            is_specialty_unreserved = cat_id in (5, 7)  # Antyodaya / Jan Sadharan have extra GS coaches

            score = 0
            if is_weekday and (is_morning_peak or is_evening_peak):
                score += 2
            elif is_morning_peak or is_evening_peak:
                score += 1

            # Monday morning & Friday evening interstate student/worker surge
            if (dow == 0 and 5 <= hour <= 10) or (dow == 4 and 15 <= hour <= 21):
                score += 1

            # Mail/Express & Superfast have fewer GS coaches -> higher density
            if cat_id in (3, 4):
                score += 1
            if is_specialty_unreserved:
                score -= 1

            label = 0 if score <= 0 else (1 if score == 1 else 2)
            X.append([hour, dow, cat_id, dist])
            y.append(label)

        self.model.fit(np.array(X), np.array(y))

    def predict(self, hour: int, day_of_week: int, category_id: int, distance_km: float) -> dict:
        features = np.array([[hour, day_of_week, category_id, distance_km]])
        pred = int(self.model.predict(features)[0])
        proba = float(np.max(self.model.predict_proba(features)))

        mapping = {
            0: {"level": "LOW", "label": "Available Seating Tiers Present", "color": "green"},
            1: {"level": "MEDIUM", "label": "Moderate Commuter Standee Load", "color": "amber"},
            2: {"level": "HIGH", "label": "Heavy Volume - Expect High Density", "color": "red"},
        }
        res = mapping[pred].copy()
        res["confidence"] = round(proba * 100, 1)
        return res

predictor = CrowdPredictor()
