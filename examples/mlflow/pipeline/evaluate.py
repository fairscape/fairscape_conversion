"""Step 3: score the best model on test.csv. Run: evaluate (usedMLModel -> the model)."""
from common import DATA, EXPERIMENT, MODEL_ID_FILE, TRACKING

import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.entities import LoggedModelInput
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score, classification_report,
                             confusion_matrix, f1_score)

mlflow.set_tracking_uri(TRACKING)
mlflow.set_experiment(EXPERIMENT)

model_id = MODEL_ID_FILE.read_text().strip()
model = mlflow.sklearn.load_model(f"models:/{model_id}")
test = pd.read_csv(DATA / "test.csv")
X, y = test.drop(columns="species"), test.species

with mlflow.start_run(run_name="evaluate"):
    mlflow.log_input(mlflow.data.from_pandas(test, name="iris-test", targets="species",
                                             source=str(DATA / "test.csv")), context="evaluation")
    mlflow.log_input(model=LoggedModelInput(model_id))          # this run *used* the model
    mlflow.log_params({"model_id": model_id, "threshold": "argmax"})

    predicted = model.predict(X)
    mlflow.log_metrics({"accuracy": accuracy_score(y, predicted),
                        "f1_macro": f1_score(y, predicted, average="macro")})

    out = DATA / "evaluation"; out.mkdir(exist_ok=True)
    test.assign(predicted=predicted).to_csv(out / "predictions.csv", index=False)
    pd.DataFrame(confusion_matrix(y, predicted)).to_csv(out / "confusion_matrix.csv", index=False)
    (out / "classification_report.json").write_text(
        json.dumps(classification_report(y, predicted, output_dict=True), indent=2))
    ConfusionMatrixDisplay.from_predictions(y, predicted, display_labels=["setosa", "versicolor", "virginica"])
    plt.title("Iris test set")
    plt.savefig(out / "confusion_matrix.png", dpi=120, bbox_inches="tight")
    mlflow.log_artifacts(out, artifact_path="evaluation")

print(f"evaluate: accuracy {accuracy_score(y, predicted):.3f} on {len(test)} test rows")
