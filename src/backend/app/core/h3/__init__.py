"""H3 Ref2VA prompt composition/validation and frame grid."""

from .frames import frames_for_audio_seconds, frames_for_seconds
from .prompt import (
    SECTION_KEYS,
    USER_PROMPT_META_KEY,
    compose_h3_prompt,
    merge_user_locked_prompt,
    stamp_user_prompt_lock,
    user_locked_prompt_dict,
    validate_h3_prompt,
    validate_required_picture_bindings,
)

__all__ = [
    "SECTION_KEYS",
    "USER_PROMPT_META_KEY",
    "compose_h3_prompt",
    "merge_user_locked_prompt",
    "stamp_user_prompt_lock",
    "user_locked_prompt_dict",
    "frames_for_seconds",
    "frames_for_audio_seconds",
    "validate_h3_prompt",
    "validate_required_picture_bindings",
]
