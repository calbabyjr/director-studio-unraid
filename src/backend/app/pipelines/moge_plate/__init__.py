from .pipeline import MogePlatePipeline
from ..registry import register_pipeline

MOGE_PLATE_PIPELINE = register_pipeline(MogePlatePipeline())

__all__ = ["MOGE_PLATE_PIPELINE", "MogePlatePipeline"]
