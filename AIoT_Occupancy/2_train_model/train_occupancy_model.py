"""
STEP 2 - AI Model Training
===========================
Trains two models on VL53L0X distance data:
  - OccupancyClassifier : empty vs occupied (binary, Random Forest)
  - OccupancyEstimator  : people count 0-3 (Gradient Boosting Regressor)

Usage:
    python train_occupancy_model.py                          # uses sample_dataset.csv
    python train_occupancy_model.py ../1_collect_data/dataset.csv  # real collected data
"""

import sys
import os
import json
import numpy as np
import pandas as pd
import joblib

from sklearn.ensemble import RandomForestClassifier, GradientBoostingRegressor
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, confusion_matrix, mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline

# -- ONNX optional export --
try:
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
DOOR_WIDTH_MM = 900
SENSOR_RANGE  = 2000
NOISE_STD     = 15
MODELS_DIR    = os.path.join(os.path.dirname(__file__), "models")

FEATURE_COLS = [
    "distance_mm", "dist_norm", "zone",
    "velocity", "velocity_abs", "zone_cross",
    "roll_mean_3",  "roll_std_3",  "roll_range_3",
    "roll_mean_5",  "roll_std_5",  "roll_range_5",
    "roll_mean_10", "roll_std_10", "roll_range_10",
    "roll_min_10",  "roll_max_10",
]

# ─────────────────────────────────────────────────────────────────────────────
# 1. DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────
def generate_synthetic_data(n_samples=8000, seed=42):
    rng = np.random.default_rng(seed)
    rows = []
    t = 0
    state_probs = [0.50, 0.28, 0.14, 0.08]
    state_dur   = {0:(300,1200), 1:(100,600), 2:(80,400), 3:(60,200)}
    current_state = 0
    state_timer   = 0

    for _ in range(n_samples):
        if state_timer <= 0:
            current_state = rng.choice([0,1,2,3], p=state_probs)
            lo, hi = state_dur[current_state]
            state_timer = rng.integers(lo, hi)
        if current_state == 0:
            dist = rng.uniform(DOOR_WIDTH_MM * 0.9, SENSOR_RANGE)
        elif current_state == 1:
            dist = rng.uniform(200, DOOR_WIDTH_MM * 0.55)
        elif current_state == 2:
            dist = rng.uniform(150, DOOR_WIDTH_MM * 0.45)
        else:
            dist = rng.uniform(100, DOOR_WIDTH_MM * 0.35)
        dist += rng.normal(0, NOISE_STD)
        dist  = float(np.clip(dist, 30, SENSOR_RANGE))
        rows.append({"timestamp_ms": t, "distance_mm": round(dist,1),
                     "occupancy_count": current_state})
        t += rng.integers(800, 1200)
        state_timer -= 1000
    return pd.DataFrame(rows)


def load_data(csv_path=None):
    if csv_path and os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        # Remove unlabelled rows (from collect without --label flag)
        df = df[df["occupancy_count"] >= 0].copy()
        assert {"timestamp_ms","distance_mm","occupancy_count"}.issubset(df.columns)
        print(f"[DATA] Loaded {len(df)} labelled samples from {csv_path}")
    else:
        sample = os.path.join(os.path.dirname(__file__),
                              "..", "1_collect_data", "sample_dataset.csv")
        if os.path.exists(sample):
            df = pd.read_csv(sample)
            print(f"[DATA] Using sample_dataset.csv ({len(df)} rows)")
        else:
            print("[DATA] Generating synthetic data ...")
            df = generate_synthetic_data()
    return df

# ─────────────────────────────────────────────────────────────────────────────
# 2. FEATURE ENGINEERING
# ─────────────────────────────────────────────────────────────────────────────
def engineer_features(df, windows=(3, 5, 10)):
    d    = df.copy().sort_values("timestamp_ms").reset_index(drop=True)
    dist = d["distance_mm"]

    d["zone"] = pd.cut(dist, bins=[0, 350, 700, SENSOR_RANGE+1],
                       labels=[0, 1, 2]).astype(int)

    dt = d["timestamp_ms"].diff().replace(0, np.nan)
    d["velocity"]     = dist.diff() / dt
    d["velocity"]     = d["velocity"].fillna(0)
    d["velocity_abs"] = d["velocity"].abs()

    for w in windows:
        d[f"roll_mean_{w}"]  = dist.rolling(w, min_periods=1).mean()
        d[f"roll_std_{w}"]   = dist.rolling(w, min_periods=1).std().fillna(0)
        d[f"roll_min_{w}"]   = dist.rolling(w, min_periods=1).min()
        d[f"roll_max_{w}"]   = dist.rolling(w, min_periods=1).max()
        d[f"roll_range_{w}"] = d[f"roll_max_{w}"] - d[f"roll_min_{w}"]

    d["zone_cross"] = (d["zone"].diff().abs()
                       .rolling(10, min_periods=1).sum().fillna(0))
    d["dist_norm"]  = dist / SENSOR_RANGE
    return d

# ─────────────────────────────────────────────────────────────────────────────
# 3. TRAIN
# ─────────────────────────────────────────────────────────────────────────────
def train_classifier(X_tr, yc_tr, X_te, yc_te):
    print("\n-- Binary Occupancy Classifier (Random Forest) --")
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("rf", RandomForestClassifier(
            n_estimators=200, max_depth=12,
            min_samples_leaf=5, class_weight="balanced",
            random_state=42, n_jobs=-1))
    ])
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipe, X_tr, yc_tr, cv=cv,
                             scoring="f1_weighted", n_jobs=-1)
    print(f"  CV F1 (5-fold): {scores.mean():.4f} +/- {scores.std():.4f}")
    pipe.fit(X_tr, yc_tr)
    y_pred = pipe.predict(X_te)
    print("\n  Test-set report:")
    print(classification_report(yc_te, y_pred, target_names=["empty","occupied"]))
    print("  Confusion matrix:\n", confusion_matrix(yc_te, y_pred))
    imp = pd.Series(pipe.named_steps["rf"].feature_importances_,
                    index=FEATURE_COLS).sort_values(ascending=False)
    print("\n  Top-5 features:\n", imp.head(5).to_string())
    return pipe


def train_estimator(X_tr, yr_tr, X_te, yr_te):
    print("\n-- Occupancy Count Estimator (Gradient Boosting) --")
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("gbr", GradientBoostingRegressor(
            n_estimators=300, learning_rate=0.05,
            max_depth=4, subsample=0.8, random_state=42))
    ])
    pipe.fit(X_tr, yr_tr)
    y_raw   = pipe.predict(X_te)
    y_pred  = np.clip(np.round(y_raw), 0, 3).astype(int)
    print(f"  MAE : {mean_absolute_error(yr_te, y_raw):.4f}")
    print(f"  R2  : {r2_score(yr_te, y_raw):.4f}")
    print("\n  Per-count accuracy:")
    for c in range(4):
        mask = yr_te == c
        if mask.sum() > 0:
            acc = (y_pred[mask] == c).mean()
            print(f"    count={c}: {acc:.2%}  (n={mask.sum()})")
    return pipe

# ─────────────────────────────────────────────────────────────────────────────
# 4. ONNX EXPORT
# ─────────────────────────────────────────────────────────────────────────────
def export_onnx(pipeline, name, n_features, out_dir):
    if not ONNX_AVAILABLE:
        return
    initial_type = [("float_input", FloatTensorType([None, n_features]))]
    onnx_model   = convert_sklearn(pipeline, initial_types=initial_type,
                                   target_opset=17)
    path = os.path.join(out_dir, f"{name}.onnx")
    with open(path, "wb") as f:
        f.write(onnx_model.SerializeToString())
    print(f"  [ONNX] {path}")

# ─────────────────────────────────────────────────────────────────────────────
# INFERENCE CLASS  (imported by server.py)
# ─────────────────────────────────────────────────────────────────────────────
class OccupancyInference:
    """Used by FastAPI server."""
    def __init__(self, model_dir=MODELS_DIR):
        self.clf  = joblib.load(os.path.join(model_dir, "classifier.pkl"))
        self.reg  = joblib.load(os.path.join(model_dir, "estimator.pkl"))
        self._buf = []

    def predict(self, distance_mm: float) -> dict:
        self._buf.append({"timestamp_ms": len(self._buf)*1000,
                          "distance_mm": distance_mm,
                          "occupancy_count": 0})
        df  = pd.DataFrame(self._buf[-10:])
        fe  = engineer_features(df)
        row = fe.iloc[[-1]][FEATURE_COLS].fillna(0)

        proba    = self.clf.predict_proba(row)[0][1]
        occupied = bool(proba >= 0.5)
        count    = int(np.clip(round(self.reg.predict(row)[0]), 0, 3))

        return {
            "occupied":    occupied,
            "count":       count if occupied else 0,
            "confidence":  round(float(proba), 4),
            "distance_mm": distance_mm
        }

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else None
    os.makedirs(MODELS_DIR, exist_ok=True)

    df_raw  = load_data(csv_path)
    df_feat = engineer_features(df_raw).dropna()

    X   = df_feat[FEATURE_COLS].values
    y_c = (df_feat["occupancy_count"] > 0).astype(int).values
    y_r = df_feat["occupancy_count"].values

    X_tr, X_te, yc_tr, yc_te, yr_tr, yr_te = train_test_split(
        X, y_c, y_r, test_size=0.20, stratify=y_c, random_state=42)

    clf = train_classifier(X_tr, yc_tr, X_te, yc_te)
    reg = train_estimator(X_tr, yr_tr, X_te, yr_te)

    joblib.dump(clf, os.path.join(MODELS_DIR, "classifier.pkl"))
    joblib.dump(reg, os.path.join(MODELS_DIR, "estimator.pkl"))

    export_onnx(clf, "occupancy_classifier", len(FEATURE_COLS), MODELS_DIR)
    export_onnx(reg, "occupancy_estimator",  len(FEATURE_COLS), MODELS_DIR)

    meta = {"feature_cols": FEATURE_COLS,
            "sensor_range_mm": SENSOR_RANGE,
            "door_width_mm": DOOR_WIDTH_MM}
    with open(os.path.join(MODELS_DIR, "model_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n[SAVE] Models saved to {MODELS_DIR}")
    print("\nTraining complete.")
    print("\nNext step:  cd ../3_api_server && uvicorn server:app --reload --port 8000")


if __name__ == "__main__":
    main()
