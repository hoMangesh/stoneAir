"""Manufacturing Inference Engine.

Knowledge-based system that determines manufacturing processes and machines
for ANY product by parsing its name and inferring attributes.
"""

# Relative imports make this package importable from the backend (e.g.
# `from machine_recommender import ManufacturingRecommender`). The CLI app.py
# adds the repo root to sys.path so its bare imports still resolve when run
# directly from inside machine_recommender/.
from .recommender import ManufacturingRecommender
from .models import Machine, ManufacturingProcess, InferredProduct, WorkflowResult

__version__ = "2.0.0"
__all__ = [
    "ManufacturingRecommender",
    "Machine",
    "ManufacturingProcess",
    "InferredProduct",
    "WorkflowResult",
]
