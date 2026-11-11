"""Local Wan 2.2 image-to-video pipeline."""

from .pipeline import WanI2VPipeline
from ..registry import register_pipeline

register_pipeline(WanI2VPipeline())
