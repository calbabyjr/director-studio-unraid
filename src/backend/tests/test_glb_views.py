from __future__ import annotations

import json
import struct
from io import BytesIO

from PIL import Image

from app.core.media.glb_views import GlbError, load_glb_mesh, render_moge_views


def _glb(doc: dict, blob: bytes) -> bytes:
    json_bytes = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    json_pad = (4 - len(json_bytes) % 4) % 4
    json_bytes += b" " * json_pad
    bin_pad = (4 - len(blob) % 4) % 4
    blob_padded = blob + (b"\x00" * bin_pad)
    chunks = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    chunks += struct.pack("<II", len(blob_padded), 0x004E4942) + blob_padded
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def colored_triangle_glb() -> bytes:
    positions = struct.pack("<9f", -1.0, -1.0, 0.0, 1.0, -1.0, 0.0, 0.0, 1.0, 0.0)
    colors = struct.pack("<9f", 1.0, 0.1, 0.1, 0.1, 1.0, 0.1, 0.1, 0.1, 1.0)
    indices = struct.pack("<3H", 0, 1, 2)
    blob = positions + colors + indices
    doc = {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "COLOR_0": 1},
                        "indices": 2,
                    }
                ]
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "max": [1.0, 1.0, 0.0],
                "min": [-1.0, -1.0, 0.0],
            },
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 36},
            {"buffer": 0, "byteOffset": 72, "byteLength": 6},
        ],
        "buffers": [{"byteLength": len(blob)}],
    }
    return _glb(doc, blob)


def test_load_glb_rejects_non_mesh():
    try:
        load_glb_mesh(b"not a glb")
    except GlbError as exc:
        assert "glb" in str(exc).lower()
    else:
        raise AssertionError("expected GlbError")


def test_render_moge_views_returns_three_pngs():
    views = render_moge_views(colored_triangle_glb(), size=96)
    assert set(views) == {"front", "orbit", "back"}
    for png in views.values():
        image = Image.open(BytesIO(png))
        assert image.size == (96, 96)
        assert image.mode == "RGB"
        extrema = image.getextrema()
        # Not a flat background — at least one channel spans a range.
        assert any(lo != hi for lo, hi in extrema)


def test_load_glb_keeps_only_referenced_vertices():
    mesh = load_glb_mesh(colored_triangle_glb())
    assert len(mesh.positions) == 3
    assert len(mesh.faces) == 1
    assert mesh.colors is not None
    assert len(mesh.colors) == 3
