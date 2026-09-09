"""Shared settings for the pipeline scripts. Import this before mlflow."""
import os
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"                                   # files the steps hand each other
CRATE = HERE / "crate"                                 # where the RO-Crate lands
TRACKING = f"sqlite:///{HERE / 'mlflow.db'}"           # any MLflow tracking URI works
EXPERIMENT = "iris-pipeline"
MODEL_ID_FILE = DATA / "best_model_id.txt"             # train.py -> evaluate.py

os.environ["MLFLOW_LOGGING_LEVEL"] = "ERROR"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR"] = "false"
warnings.filterwarnings("ignore", category=UserWarning)
DATA.mkdir(exist_ok=True)
