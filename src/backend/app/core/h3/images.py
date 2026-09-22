"""Pack H3 Picture bytes from shot refs."""

from __future__ import annotations

from ..library.images import resolve_asset_image
from ..library.store import load_asset
from ..projects.models import Shot, ShotRef
from ..schemas import LibraryAsset

_ROLE_KIND = {
    "actor": "actors",
    "costume": "costumes",
    "scene": "scenes",
    "prop": "props",
    "layout_ref_frame": "layouts",
    "other": "props",
}
_LIBRARY_KINDS = ("actors", "scenes", "props", "costumes", "layouts")


def load_ref_asset(ref: ShotRef) -> LibraryAsset | None:
    kind = _ROLE_KIND.get(ref.role.value)
    if kind:
        asset = load_asset(kind, ref.asset_id)
        if asset:
            return asset
    for item in _LIBRARY_KINDS:
        asset = load_asset(item, ref.asset_id)
        if asset:
            return asset
    return None


def collect_h3_images(shot: Shot) -> dict[str, tuple[str, bytes]]:
    images: dict[str, tuple[str, bytes]] = {}
    ordered = sorted(shot.refs or [], key=lambda ref: ref.picture_index)
    if len(ordered) > 9:
        raise ValueError("H3 supports at most 9 image refs")
    for ref in ordered:
        asset = load_ref_asset(ref)
        if not asset:
            raise ValueError(
                f"missing library asset for ref picture {ref.picture_index}: {ref.asset_id}"
            )
        hit = resolve_asset_image(asset, role=ref.role.value, file_key=ref.file_key)
        if not hit:
            raise ValueError(
                f"no image file for ref picture {ref.picture_index}: {ref.asset_id}"
            )
        name, data, _key = hit
        images[f"ref_{len(images)}"] = (name, data)
    if not images:
        raise ValueError("at least one image ref is required for H3 submit")
    return images
