"""Cast an Actor as a person pack: extra stills plus linked Voice."""

from __future__ import annotations

from ..library.store import load_asset
from ..schemas import LibraryAsset
from .layouts import RefRole
from .models import Shot, ShotRef, ShotVoiceRef

PACK_VIEW_KEYS = (
    "fullbody_threeview",
    "bust_threeview",
    "master",
    "face",
    "profile",
    "back",
    "threeview_extra",
)
MAX_PICTURES = 9
MAX_VOICES = 3


def actor_pack_status(asset: LibraryAsset) -> dict[str, object]:
    files = dict(asset.files or {})
    views = {
        key: bool(files.get(key))
        for key in PACK_VIEW_KEYS
        if not str(key).startswith("voice")
    }
    linked = [str(item) for item in (asset.meta or {}).get("linked_voice_ids") or [] if item]
    has_identity = bool(views.get("fullbody_threeview") or views.get("master") or views.get("face"))
    return {
        "actor_id": asset.id,
        "name": asset.name,
        "views": views,
        "view_count": sum(1 for present in views.values() if present),
        "linked_voice_ids": linked,
        "has_voice": bool(linked),
        "ready": has_identity,
    }


def picture_keys_for_actor(asset: LibraryAsset) -> list[str]:
    files = dict(asset.files or {})
    keys: list[str] = []
    for key in PACK_VIEW_KEYS:
        name = files.get(key)
        if not name:
            continue
        if str(key).startswith("voice"):
            continue
        suffix = str(name).rsplit(".", 1)[-1].lower()
        if suffix in {"wav", "mp3", "m4a", "aac", "flac", "ogg"}:
            continue
        keys.append(key)
    return keys


def linked_voice_asset(actor: LibraryAsset) -> LibraryAsset | None:
    for voice_id in (actor.meta or {}).get("linked_voice_ids") or []:
        voice = load_asset("voices", str(voice_id))
        if voice is not None and bool((voice.meta or {}).get("h3_ready")):
            return voice
    return None


def cast_actor_on_shot(shot: Shot, actor_id: str) -> Shot:
    actor = load_asset("actors", actor_id)
    if actor is None:
        raise ValueError(f"actor not found: {actor_id}")
    if actor.project_id and shot.project_id and actor.project_id != shot.project_id:
        raise ValueError("actor belongs to another project")
    keys = picture_keys_for_actor(actor)
    if not keys:
        raise ValueError("actor has no stills to bind as Pictures")

    kept = [ref for ref in shot.refs if not (ref.role == RefRole.actor and ref.asset_id == actor_id)]
    remaining = MAX_PICTURES - len(kept)
    if remaining < 1:
        raise ValueError("shot already has 9 Pictures; remove one before casting this actor")
    new_actor_refs = [
        ShotRef(role=RefRole.actor, asset_id=actor.id, picture_index=1, file_key=key)
        for key in keys[:remaining]
    ]
    merged = kept + new_actor_refs
    reindexed = [
        ref.model_copy(update={"picture_index": index})
        for index, ref in enumerate(merged, start=1)
    ]

    voices = [
        ref
        for ref in shot.voice_refs
        if ref.asset_id not in set((actor.meta or {}).get("linked_voice_ids") or [])
    ]
    linked = linked_voice_asset(actor)
    if linked is not None and all(ref.asset_id != linked.id for ref in voices):
        if len(voices) >= MAX_VOICES:
            voices = voices[: MAX_VOICES - 1]
        voices.append(
            ShotVoiceRef(
                asset_id=linked.id,
                audio_index=1,
                file_key="reference",
                speaker=actor.name,
            )
        )
    voices = [
        ref.model_copy(update={"audio_index": index})
        for index, ref in enumerate(voices, start=1)
    ]
    return shot.model_copy(update={"refs": reindexed, "voice_refs": voices})
