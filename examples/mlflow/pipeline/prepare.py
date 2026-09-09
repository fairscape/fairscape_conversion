"""Step 1: split iris into train/test CSVs. Run: prepare-data."""
from common import DATA, EXPERIMENT, TRACKING

import mlflow
import pandas as pd
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split

TEST_SIZE, SEED = 0.25, 0

mlflow.set_tracking_uri(TRACKING)
mlflow.set_experiment(EXPERIMENT)

with mlflow.start_run(run_name="prepare-data"):
    mlflow.log_params({"test_size": TEST_SIZE, "random_state": SEED, "stratify": "species"})

    features, target = load_iris(return_X_y=True, as_frame=True)
    iris = features.assign(species=target)
    mlflow.log_input(mlflow.data.from_pandas(iris, name="iris", targets="species"), context="source")

    train, test = train_test_split(iris, test_size=TEST_SIZE, random_state=SEED, stratify=iris.species)
    train.to_csv(DATA / "train.csv", index=False)
    test.to_csv(DATA / "test.csv", index=False)
    mlflow.log_artifacts(DATA, artifact_path="data")
    mlflow.log_metrics({"train_rows": len(train), "test_rows": len(test)})

print(f"prepare-data: {len(train)} train rows, {len(test)} test rows")
