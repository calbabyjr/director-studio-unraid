from .pipeline import CostumePipeline
from ..registry import register_pipeline

COSTUME_PIPELINE = register_pipeline(CostumePipeline())

__all__ = ["COSTUME_PIPELINE", "CostumePipeline"]
