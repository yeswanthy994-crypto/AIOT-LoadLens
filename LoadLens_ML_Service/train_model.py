import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib
import os

CSV_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "LoadLens_P03", "loadlens_telemetry.csv"))
MODEL_FILE = os.path.join(os.path.dirname(__file__), "loadlens_ml_model.joblib")

def generate_synthetic_augmentation(df):
    """
    Augments logged data with realistic thermodynamic boundary samples
    to ensure full class coverage (FREE, PARTIAL, HEAVY) even if logged data is limited.
    """
    np.random.seed(42)
    # Class 0: FREE (< 40 C)
    free_temps = np.random.uniform(22.0, 39.5, 300)
    free_bases = np.random.uniform(22.0, 30.0, 300)
    free_rises = np.maximum(0.0, free_temps - free_bases)
    free_states = ["FREE"] * 300

    # Class 1: PARTIAL (40.0 - 49.9 C)
    part_temps = np.random.uniform(40.0, 49.8, 300)
    part_bases = np.random.uniform(25.0, 32.0, 300)
    part_rises = part_temps - part_bases
    part_states = ["PARTIAL"] * 300

    # Class 2: HEAVY (>= 50.0 C)
    heavy_temps = np.random.uniform(50.0, 68.0, 300)
    heavy_bases = np.random.uniform(26.0, 34.0, 300)
    heavy_rises = heavy_temps - heavy_bases
    heavy_states = ["HEAVY"] * 300

    aug_df = pd.DataFrame({
        "Temperature_C": np.concatenate([free_temps, part_temps, heavy_temps]),
        "Baseline_C": np.concatenate([free_bases, part_bases, heavy_bases]),
        "Rise_Delta_C": np.concatenate([free_rises, part_rises, heavy_rises]),
        "Airflow_State": np.concatenate([free_states, part_states, heavy_states])
    })
    return aug_df

def train():
    print("=" * 60)
    print(" LoadLens Machine Learning Training Pipeline")
    print("=" * 60)

    # 1. Load real logged data
    real_df = None
    if os.path.exists(CSV_FILE) and os.path.getsize(CSV_FILE) > 100:
        try:
            real_df = pd.read_csv(CSV_FILE)
            print(f"[DATA] Loaded {len(real_df)} real telemetry rows from {CSV_FILE}")
        except Exception as e:
            print(f"[WARN] Error reading CSV: {e}")

    # 2. Augment dataset
    aug_df = generate_synthetic_augmentation(real_df)
    if real_df is not None and not real_df.empty:
        # Combine real + augmented
        features_needed = ["Temperature_C", "Baseline_C", "Rise_Delta_C", "Airflow_State"]
        if all(col in real_df.columns for col in features_needed):
            clean_real = real_df[features_needed].dropna()
            combined_df = pd.concat([clean_real, aug_df], ignore_index=True)
        else:
            combined_df = aug_df
    else:
        combined_df = aug_df

    # 3. Prepare Feature Matrix X and Target y
    X = combined_df[["Temperature_C", "Baseline_C", "Rise_Delta_C"]]
    y = combined_df["Airflow_State"]

    # 4. Train/Test Split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    # 5. Train Random Forest Classifier
    clf = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    clf.fit(X_train, y_train)

    # 6. Evaluate
    y_pred = clf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"\n[EVALUATION] Model Accuracy: {acc * 100:.2f}%\n")
    print(classification_report(y_test, y_pred))

    # 7. Save Model
    joblib.dump(clf, MODEL_FILE)
    print(f"[OK] Trained model serialized to: {MODEL_FILE}")

if __name__ == "__main__":
    train()
