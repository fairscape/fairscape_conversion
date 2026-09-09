"""Step 2: train a few random forests on train.csv, keep the best. Run: train (+ one nested run per candidate)."""
from common import DATA, EXPERIMENT, MODEL_ID_FILE, TRACKING

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

CANDIDATES = [
    {"n_estimators": 50,  "max_depth": 2},
    {"n_estimators": 200, "max_depth": 4},
    {"n_estimators": 400, "max_depth": None},
]
SEED = 0

mlflow.set_tracking_uri(TRACKING)
mlflow.set_experiment(EXPERIMENT)

train = pd.read_csv(DATA / "train.csv")
X, y = train.drop(columns="species"), train.species
train_set = mlflow.data.from_pandas(train, name="iris-train", targets="species",
                                    source=str(DATA / "train.csv"))   # the file prepare-data wrote

best = None
with mlflow.start_run(run_name="train"):
    mlflow.log_input(train_set, context="training")
    mlflow.log_param("selection_metric", "oob_accuracy")

    for params in CANDIDATES:
        with mlflow.start_run(run_name=f"rf-{params['n_estimators']}-trees", nested=True):
            mlflow.log_input(train_set, context="training")
            mlflow.log_params({**params, "random_state": SEED})

            forest = RandomForestClassifier(**params, random_state=SEED, oob_score=True).fit(X, y)
            mlflow.log_metric("oob_accuracy", forest.oob_score_)
            info = mlflow.sklearn.log_model(forest, name="iris-rf", input_example=X.head(3),
                                            serialization_format="pickle")

            if best is None or forest.oob_score_ > best[0]:
                best = (forest.oob_score_, info.model_id, params)

    mlflow.log_metric("best_oob_accuracy", best[0])
    mlflow.log_params({f"best_{k}": v for k, v in best[2].items()})
    mlflow.set_tag("best_model_id", best[1])

MODEL_ID_FILE.write_text(best[1])
print(f"train: best candidate {best[2]} (oob accuracy {best[0]:.3f}) -> {best[1]}")
