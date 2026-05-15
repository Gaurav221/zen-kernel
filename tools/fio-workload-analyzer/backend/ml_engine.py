"""
ML engine for drive behaviour analysis.

Models:
  1. AnomalyDetector     — Isolation Forest on performance metrics
  2. DriveAgeRegressor   — Gradient Boosting → estimated % NAND wear used
  3. FWFingerprint       — K-Means clustering → firmware algorithm fingerprint
  4. PerfTrendForecaster — Polynomial regression → IOPS at future write count
  5. HealthScorer        — Composite rule + ML score → 0-100 health %
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from .config import MODELS_DIR
from .database import MLModel, FIOResult

warnings.filterwarnings("ignore")

# Canonical feature list — must be the same at train and inference time
FEATURES = [
    "total_iops", "total_bw_mbps",
    "read_iops", "write_iops",
    "read_bw_mbps", "write_bw_mbps",
    "read_lat_mean_us", "write_lat_mean_us",
    "read_p50_us", "read_p99_us", "read_p999_us",
    "write_p50_us", "write_p99_us", "write_p999_us",
    "iops_stability", "lat_tail_ratio",
    "write_amp_est", "gc_pause_score",
    "log2_bs", "log2_qd", "rw_encoded",
    "n_perf_cliffs",
    "read_iops_cv", "write_iops_cv",
    "read_lat_us_cv", "write_lat_us_cv",
]


def _fill_missing(vec: dict) -> np.ndarray:
    return np.array([float(vec.get(f, 0.0) or 0.0) for f in FEATURES]).reshape(1, -1)


# --------------------------------------------------------------------------- #
#  1. Anomaly Detector                                                         #
# --------------------------------------------------------------------------- #

class AnomalyDetector:
    MODEL_NAME = "anomaly_detector"

    def __init__(self):
        self.model: Optional[IsolationForest] = None
        self.scaler = StandardScaler()

    def train(self, feature_vecs: list[dict], contamination: float = 0.05) -> dict:
        if len(feature_vecs) < 10:
            return {"error": "need at least 10 samples"}
        X = np.vstack([_fill_missing(v) for v in feature_vecs])
        X_scaled = self.scaler.fit_transform(X)
        self.model = IsolationForest(contamination=contamination, random_state=42, n_estimators=200)
        self.model.fit(X_scaled)
        labels = self.model.predict(X_scaled)
        n_anomalies = int((labels == -1).sum())
        self._save()
        return {"n_samples": len(feature_vecs), "n_anomalies": n_anomalies,
                "contamination": contamination}

    def predict(self, vec: dict) -> dict:
        if self.model is None:
            return {"error": "model not trained"}
        X = self.scaler.transform(_fill_missing(vec))
        label = int(self.model.predict(X)[0])
        score = float(self.model.score_samples(X)[0])
        return {
            "is_anomaly": label == -1,
            "anomaly_score": round(score, 4),
            "interpretation": "normal" if label == 1 else "anomalous",
        }

    def _save(self):
        path = MODELS_DIR / f"{self.MODEL_NAME}.joblib"
        joblib.dump({"model": self.model, "scaler": self.scaler}, path)

    @classmethod
    def load(cls) -> "AnomalyDetector":
        inst = cls()
        path = MODELS_DIR / f"{cls.MODEL_NAME}.joblib"
        if path.exists():
            data = joblib.load(path)
            inst.model  = data["model"]
            inst.scaler = data["scaler"]
        return inst


# --------------------------------------------------------------------------- #
#  2. Drive Age Regressor                                                      #
# --------------------------------------------------------------------------- #

class DriveAgeRegressor:
    """
    Predicts estimated % NAND wear consumed, given:
    - Feature vector (performance metrics)
    - Optionally supplemented by SMART percentage_used

    Without ground-truth labels (actual % wear), we use a proxy label built
    from gc_pause_score + write_amp_est + lat_tail_ratio, which correlates
    with actual NAND wear.
    """
    MODEL_NAME = "drive_age_regressor"

    def __init__(self):
        self.pipeline: Optional[Pipeline] = None

    def train(self, feature_vecs: list[dict], labels: Optional[list[float]] = None) -> dict:
        if len(feature_vecs) < 5:
            return {"error": "need at least 5 samples"}

        X = np.vstack([_fill_missing(v) for v in feature_vecs])

        if labels is None:
            # Proxy label: 0–100 wear % estimated from available signals
            labels = [self._proxy_label(v) for v in feature_vecs]

        y = np.array(labels, dtype=float)
        self.pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("model",  GradientBoostingRegressor(
                n_estimators=200, max_depth=4, learning_rate=0.05,
                subsample=0.8, random_state=42,
            )),
        ])
        self.pipeline.fit(X, y)
        train_score = self.pipeline.score(X, y)
        self._save()
        return {"n_samples": len(feature_vecs), "train_r2": round(float(train_score), 4)}

    def predict(self, vec: dict) -> dict:
        if self.pipeline is None:
            return {"error": "model not trained"}
        X = _fill_missing(vec)
        pred = float(self.pipeline.predict(X)[0])
        pred = max(0.0, min(100.0, pred))
        return {
            "estimated_wear_pct": round(pred, 1),
            "health_pct": round(100.0 - pred, 1),
            "interpretation": self._interpret(pred),
        }

    @staticmethod
    def _proxy_label(vec: dict) -> float:
        gc  = float(vec.get("gc_pause_score", 0) or 0)
        wa  = float(vec.get("write_amp_est", 1) or 1)
        tr  = float(vec.get("lat_tail_ratio", 1) or 1)
        stab = float(vec.get("iops_stability", 0) or 0)
        # Rough mapping: new drive → low values, worn drive → high values
        score = (gc * 40) + ((wa - 1) * 10) + (min(tr / 100, 1) * 30) + (min(stab, 1) * 20)
        return min(max(score, 0), 100)

    @staticmethod
    def _interpret(wear_pct: float) -> str:
        if wear_pct < 20:   return "New / very healthy"
        if wear_pct < 50:   return "Healthy"
        if wear_pct < 75:   return "Moderate wear"
        if wear_pct < 90:   return "High wear — monitor"
        return "Critical — replace soon"

    def _save(self):
        path = MODELS_DIR / f"{self.MODEL_NAME}.joblib"
        joblib.dump({"pipeline": self.pipeline}, path)

    @classmethod
    def load(cls) -> "DriveAgeRegressor":
        inst = cls()
        path = MODELS_DIR / f"{cls.MODEL_NAME}.joblib"
        if path.exists():
            data = joblib.load(path)
            inst.pipeline = data["pipeline"]
        return inst


# --------------------------------------------------------------------------- #
#  3. Firmware Algorithm Fingerprinter                                         #
# --------------------------------------------------------------------------- #

FW_CLUSTER_LABELS = {
    0: "Log-structured (LFS-like)",
    1: "Copy-on-Write (B-tree)",
    2: "Hybrid (tiered buffering)",
    3: "Aggressive GC (high WA)",
    4: "Low-latency optimized",
}

class FWFingerprint:
    """
    Clusters performance fingerprints to infer firmware algorithm family.
    The cluster labels are heuristic — interpret in context.
    """
    MODEL_NAME = "fw_fingerprint"
    N_CLUSTERS = 5

    def __init__(self):
        self.scaler = StandardScaler()
        self.kmeans: Optional[KMeans] = None

    def train(self, feature_vecs: list[dict]) -> dict:
        if len(feature_vecs) < self.N_CLUSTERS:
            return {"error": f"need at least {self.N_CLUSTERS} samples"}
        X = np.vstack([_fill_missing(v) for v in feature_vecs])
        X_scaled = self.scaler.fit_transform(X)
        self.kmeans = KMeans(n_clusters=self.N_CLUSTERS, random_state=42, n_init=10)
        self.kmeans.fit(X_scaled)
        inertia = float(self.kmeans.inertia_)
        self._save()
        return {"n_clusters": self.N_CLUSTERS, "inertia": round(inertia, 2),
                "n_samples": len(feature_vecs)}

    def predict(self, vec: dict) -> dict:
        if self.kmeans is None:
            return {"error": "model not trained"}
        X = self.scaler.transform(_fill_missing(vec))
        cluster = int(self.kmeans.predict(X)[0])
        # Distance to centroid (lower → more confident)
        centroid = self.kmeans.cluster_centers_[cluster]
        dist = float(np.linalg.norm(X - centroid))
        return {
            "cluster_id":  cluster,
            "fw_label":    FW_CLUSTER_LABELS.get(cluster, f"Cluster {cluster}"),
            "confidence":  round(max(0.0, 1.0 - dist / 5.0), 2),
            "centroid_dist": round(dist, 4),
        }

    def _save(self):
        path = MODELS_DIR / f"{self.MODEL_NAME}.joblib"
        joblib.dump({"scaler": self.scaler, "kmeans": self.kmeans}, path)

    @classmethod
    def load(cls) -> "FWFingerprint":
        inst = cls()
        path = MODELS_DIR / f"{cls.MODEL_NAME}.joblib"
        if path.exists():
            data = joblib.load(path)
            inst.scaler = data["scaler"]
            inst.kmeans = data["kmeans"]
        return inst


# --------------------------------------------------------------------------- #
#  4. Performance Trend Forecaster                                             #
# --------------------------------------------------------------------------- #

class PerfTrendForecaster:
    """
    Given a sequence of (tbw_gb, iops) measurements from multiple tests,
    fit a polynomial regression to predict future IOPS at given TBW.
    """
    MODEL_NAME = "perf_trend_forecaster"

    def __init__(self):
        self.pipeline: Optional[Pipeline] = None
        self.max_tbw: float = 0.0

    def train(self, tbw_gb: list[float], iops: list[float]) -> dict:
        if len(tbw_gb) < 3:
            return {"error": "need at least 3 time points"}
        X = np.array(tbw_gb).reshape(-1, 1)
        y = np.array(iops)
        self.max_tbw = float(max(tbw_gb))
        self.pipeline = Pipeline([
            ("poly",   PolynomialFeatures(degree=2, include_bias=False)),
            ("scaler", StandardScaler()),
            ("model",  Ridge(alpha=1.0)),
        ])
        self.pipeline.fit(X, y)
        r2 = float(self.pipeline.score(X, y))
        self._save()
        return {"n_points": len(tbw_gb), "r2": round(r2, 4), "max_tbw_gb": self.max_tbw}

    def predict(self, tbw_gb_list: list[float]) -> list[dict]:
        if self.pipeline is None:
            return [{"error": "model not trained"}]
        X = np.array(tbw_gb_list).reshape(-1, 1)
        preds = self.pipeline.predict(X)
        return [
            {
                "tbw_gb": tbw,
                "predicted_iops": round(float(p), 0),
                "extrapolated": tbw > self.max_tbw,
            }
            for tbw, p in zip(tbw_gb_list, preds)
        ]

    def _save(self):
        path = MODELS_DIR / f"{self.MODEL_NAME}.joblib"
        joblib.dump({"pipeline": self.pipeline, "max_tbw": self.max_tbw}, path)

    @classmethod
    def load(cls) -> "PerfTrendForecaster":
        inst = cls()
        path = MODELS_DIR / f"{cls.MODEL_NAME}.joblib"
        if path.exists():
            data = joblib.load(path)
            inst.pipeline = data["pipeline"]
            inst.max_tbw  = data["max_tbw"]
        return inst


# --------------------------------------------------------------------------- #
#  5. Health Scorer (rule + ML composite)                                     #
# --------------------------------------------------------------------------- #

def compute_health_score(
    result: FIOResult,
    smart_available_spare: Optional[float] = None,
    smart_pct_used: Optional[float] = None,
    age_prediction: Optional[dict] = None,
    anomaly_prediction: Optional[dict] = None,
) -> dict:
    """
    Composite 0-100 health score from:
    - ML age regressor output
    - SMART available spare %
    - SMART percentage used
    - Anomaly score
    - Performance tail ratio
    """
    score = 100.0
    reasons = []

    if smart_pct_used is not None:
        deduction = min(smart_pct_used * 0.8, 80)
        score -= deduction
        reasons.append(f"SMART: {smart_pct_used}% NAND used (−{deduction:.1f})")

    if smart_available_spare is not None and smart_available_spare < 10:
        d = (10 - smart_available_spare) * 2
        score -= d
        reasons.append(f"Low spare ({smart_available_spare}%) (−{d:.1f})")

    if age_prediction and "estimated_wear_pct" in age_prediction:
        w = age_prediction["estimated_wear_pct"]
        d = w * 0.2
        score -= d
        reasons.append(f"Estimated wear {w}% (−{d:.1f})")

    if anomaly_prediction and anomaly_prediction.get("is_anomaly"):
        score -= 15
        reasons.append("Anomalous performance detected (−15)")

    if result.lat_tail_ratio and result.lat_tail_ratio > 50:
        d = min((result.lat_tail_ratio - 50) / 10, 20)
        score -= d
        reasons.append(f"High latency tail ratio {result.lat_tail_ratio:.0f}× (−{d:.1f})")

    score = max(0.0, min(100.0, score))

    return {
        "health_score": round(score, 1),
        "grade": _grade(score),
        "reasons": reasons,
    }


def _grade(score: float) -> str:
    if score >= 90: return "A"
    if score >= 75: return "B"
    if score >= 60: return "C"
    if score >= 40: return "D"
    return "F"


# --------------------------------------------------------------------------- #
#  Model registry helpers                                                      #
# --------------------------------------------------------------------------- #

_INSTANCES: dict[str, object] = {}

def get_anomaly_detector() -> AnomalyDetector:
    if "anomaly" not in _INSTANCES:
        _INSTANCES["anomaly"] = AnomalyDetector.load()
    return _INSTANCES["anomaly"]

def get_age_regressor() -> DriveAgeRegressor:
    if "age" not in _INSTANCES:
        _INSTANCES["age"] = DriveAgeRegressor.load()
    return _INSTANCES["age"]

def get_fw_fingerprint() -> FWFingerprint:
    if "fw" not in _INSTANCES:
        _INSTANCES["fw"] = FWFingerprint.load()
    return _INSTANCES["fw"]

def get_trend_forecaster() -> PerfTrendForecaster:
    if "trend" not in _INSTANCES:
        _INSTANCES["trend"] = PerfTrendForecaster.load()
    return _INSTANCES["trend"]
