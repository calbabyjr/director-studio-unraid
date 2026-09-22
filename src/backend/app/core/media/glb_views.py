"""Render extra camera stills from a MoGe / glTF binary mesh."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw

_GLB_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_COMPONENT = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_VEC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_MAX_FACES = 40_000
_MAX_TEXTURE = 2048
RENDER_SIZE = 768
_MODE_TRIANGLES = 4


class GlbError(ValueError):
    """Raised when a 3D file cannot be parsed or rendered."""


@dataclass
class Mesh:
    positions: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]
    colors: list[tuple[float, float, float]] | None
    uvs: list[tuple[float, float]] | None
    texture: Image.Image | None


def render_moge_views(glb_bytes: bytes, *, size: int = RENDER_SIZE) -> dict[str, bytes]:
    """Return PNG stills keyed front / orbit / back."""
    mesh = load_glb_mesh(glb_bytes)
    return {
        "front": render_mesh_view(mesh, yaw_deg=0.0, pitch_deg=8.0, size=size),
        "orbit": render_mesh_view(mesh, yaw_deg=45.0, pitch_deg=12.0, size=size),
        "back": render_mesh_view(mesh, yaw_deg=180.0, pitch_deg=8.0, size=size),
    }


def load_glb_mesh(data: bytes) -> Mesh:
    if len(data) < 12 or data[:4] != _GLB_MAGIC:
        raise GlbError("upload a binary glTF (.glb) from MoGe")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise GlbError("only glTF 2.0 .glb files are supported")
    if length > len(data):
        length = len(data)
    offset = 12
    json_doc: dict[str, Any] | None = None
    blob = b""
    while offset + 8 <= length:
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        end = min(offset + chunk_len, length)
        chunk = data[offset:end]
        offset = end
        if chunk_type == _JSON_CHUNK:
            json_doc = json.loads(chunk.decode("utf-8"))
        elif chunk_type == _BIN_CHUNK:
            blob = chunk
    if not isinstance(json_doc, dict):
        raise GlbError("glTF JSON chunk is missing")
    return _mesh_from_gltf(json_doc, blob)


def _mesh_from_gltf(doc: dict[str, Any], blob: bytes) -> Mesh:
    meshes = doc.get("meshes") or []
    if not meshes:
        raise GlbError("glTF has no mesh")
    positions: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    colors: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    texture: Image.Image | None = None
    has_color = False
    has_uv = False

    for mesh in meshes:
        for prim in mesh.get("primitives") or []:
            mode = int(prim.get("mode", _MODE_TRIANGLES))
            if mode != _MODE_TRIANGLES:
                continue
            attrs = prim.get("attributes") or {}
            if "POSITION" not in attrs:
                continue
            pos = [
                (float(p[0]), float(p[1]), float(p[2]))
                for p in _read_accessor(doc, blob, int(attrs["POSITION"]))
            ]
            if not pos:
                continue
            base = len(positions)
            positions.extend(pos)
            if "COLOR_0" in attrs:
                has_color = True
                for row in _read_accessor(doc, blob, int(attrs["COLOR_0"])):
                    colors.append(
                        (float(row[0]), float(row[1]), float(row[2] if len(row) > 2 else row[0]))
                    )
            else:
                colors.extend([(0.72, 0.72, 0.74)] * len(pos))
            if "TEXCOORD_0" in attrs:
                has_uv = True
                for row in _read_accessor(doc, blob, int(attrs["TEXCOORD_0"])):
                    uvs.append((float(row[0]), float(row[1])))
            else:
                uvs.extend([(0.0, 0.0)] * len(pos))
            if prim.get("indices") is not None:
                idx = [int(row[0]) for row in _read_accessor(doc, blob, int(prim["indices"]))]
            else:
                idx = list(range(len(pos)))
            tri_count = len(idx) // 3
            step = max(1, math.ceil(tri_count / _MAX_FACES)) if tri_count > _MAX_FACES else 1
            last = base + len(pos)
            for i in range(0, len(idx) - 2, 3 * step):
                a, b, c = base + idx[i], base + idx[i + 1], base + idx[i + 2]
                if a >= last or b >= last or c >= last or a == b or b == c or a == c:
                    continue
                faces.append((a, b, c))
            if texture is None:
                texture = _load_base_color_texture(doc, blob, prim.get("material"))

    if not positions or not faces:
        raise GlbError("glTF mesh has no triangles")
    if len(faces) > _MAX_FACES:
        faces = faces[:: math.ceil(len(faces) / _MAX_FACES)]
    mesh = Mesh(
        positions=positions,
        faces=faces,
        colors=colors if has_color else None,
        uvs=uvs if has_uv else None,
        texture=texture,
    )
    return _compact_mesh(mesh)


def _compact_mesh(mesh: Mesh) -> Mesh:
    """Keep only vertices referenced by the downsampled faces."""
    remap: dict[int, int] = {}
    positions: list[tuple[float, float, float]] = []
    colors: list[tuple[float, float, float]] | None = [] if mesh.colors is not None else None
    uvs: list[tuple[float, float]] | None = [] if mesh.uvs is not None else None
    faces: list[tuple[int, int, int]] = []

    def mapped(index: int) -> int:
        existing = remap.get(index)
        if existing is not None:
            return existing
        new_index = len(positions)
        remap[index] = new_index
        positions.append(mesh.positions[index])
        if colors is not None and mesh.colors is not None:
            colors.append(mesh.colors[index])
        if uvs is not None and mesh.uvs is not None:
            uvs.append(mesh.uvs[index])
        return new_index

    for a, b, c in mesh.faces:
        faces.append((mapped(a), mapped(b), mapped(c)))
    return Mesh(positions=positions, faces=faces, colors=colors, uvs=uvs, texture=mesh.texture)


def _read_accessor(doc: dict[str, Any], blob: bytes, index: int) -> list[tuple[float, ...]]:
    accessors = doc.get("accessors") or []
    views = doc.get("bufferViews") or []
    if index < 0 or index >= len(accessors):
        raise GlbError("glTF accessor is out of range")
    acc = accessors[index]
    ctype = int(acc.get("componentType") or 5126)
    fmt, width = _COMPONENT.get(ctype, ("f", 4))
    ncomp = _VEC.get(str(acc.get("type") or "SCALAR"), 1)
    count = int(acc.get("count") or 0)
    if count <= 0:
        return []
    view_index = acc.get("bufferView")
    if view_index is None:
        return [(0.0,) * ncomp] * count
    view = views[int(view_index)]
    offset = int(view.get("byteOffset") or 0) + int(acc.get("byteOffset") or 0)
    packed = width * ncomp
    stride = int(view.get("byteStride") or 0) or packed
    scale = 1.0
    if bool(acc.get("normalized")):
        scale = {5120: 1 / 127, 5121: 1 / 255, 5122: 1 / 32767, 5123: 1 / 65535}.get(ctype, 1.0)
    layout = "<" + fmt * ncomp
    try:
        if stride == packed:
            raws = list(struct.iter_unpack(layout, blob[offset : offset + count * packed]))
        else:
            unpack = struct.Struct(layout)
            raws = [unpack.unpack_from(blob, offset + i * stride) for i in range(count)]
    except (struct.error, IndexError) as exc:
        raise GlbError("glTF buffer is truncated") from exc
    if len(raws) != count:
        raise GlbError("glTF buffer is truncated")
    if ctype == 5126:
        return [tuple(float(v) for v in row) for row in raws]
    return [tuple(float(v) * scale for v in row) for row in raws]


def _load_base_color_texture(
    doc: dict[str, Any], blob: bytes, material_index: Any
) -> Image.Image | None:
    if material_index is None:
        return None
    materials = doc.get("materials") or []
    images = doc.get("images") or []
    views = doc.get("bufferViews") or []
    try:
        material = materials[int(material_index)]
        tex = (material.get("pbrMetallicRoughness") or {}).get("baseColorTexture") or {}
        tex_index = int((doc.get("textures") or [])[int(tex["index"])]["source"])
        image = images[tex_index]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    raw: bytes | None = None
    if image.get("bufferView") is not None:
        view = views[int(image["bufferView"])]
        start = int(view.get("byteOffset") or 0)
        raw = blob[start : start + int(view.get("byteLength") or 0)]
    elif str(image.get("uri") or "").startswith("data:"):
        import base64

        uri = str(image["uri"])
        raw = base64.b64decode(uri.split(",", 1)[-1])
    if not raw:
        return None
    try:
        loaded = Image.open(BytesIO(raw))
        if hasattr(loaded, "draft"):
            loaded.draft("RGB", (_MAX_TEXTURE, _MAX_TEXTURE))
        converted = loaded.convert("RGB")
        if max(converted.size) > _MAX_TEXTURE:
            converted.thumbnail((_MAX_TEXTURE, _MAX_TEXTURE), Image.Resampling.BILINEAR)
        return converted
    except Exception:
        return None


def _sub(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: tuple[float, ...]) -> tuple[float, float, float]:
    length = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / length, a[1] / length, a[2] / length)


def _bounds(points: list[tuple[float, float, float]]) -> tuple[tuple[float, float, float], float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    radius = 0.0
    for p in points:
        d = math.sqrt(_dot(_sub(p, center), _sub(p, center)))
        if d > radius:
            radius = d
    return center, radius or 1.0


def _sample_texture(texture: Image.Image, u: float, v: float) -> tuple[int, int, int]:
    x = min(max(u, 0.0), 1.0) * (texture.width - 1)
    y = min(max(v, 0.0), 1.0) * (texture.height - 1)
    pixel = texture.getpixel((int(x), int(y)))
    if isinstance(pixel, int):
        return (pixel, pixel, pixel)
    return (int(pixel[0]), int(pixel[1]), int(pixel[2]))


def render_mesh_view(
    mesh: Mesh,
    *,
    yaw_deg: float,
    pitch_deg: float,
    size: int = RENDER_SIZE,
) -> bytes:
    center, radius = _bounds(mesh.positions)
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    dist = radius * 2.6
    eye = (
        center[0] + dist * math.cos(pitch) * math.sin(yaw),
        center[1] + dist * math.sin(pitch),
        center[2] + dist * math.cos(pitch) * math.cos(yaw),
    )
    forward = _norm(_sub(center, eye))
    right = _cross(forward, (0.0, 1.0, 0.0))
    if _dot(right, right) < 1e-10:
        right = _cross(forward, (1.0, 0.0, 0.0))
    right = _norm(right)
    up = _cross(right, forward)
    focal = size * 0.9
    cx = cy = size / 2
    light = _norm((0.35, 0.8, 0.45))
    near = radius * 0.02

    cam: list[tuple[float, float, float] | None] = []
    for pos in mesh.positions:
        rel = _sub(pos, eye)
        z = _dot(rel, forward)
        if z <= near:
            cam.append(None)
            continue
        x = _dot(rel, right)
        y = _dot(rel, up)
        cam.append((cx + focal * x / z, cy - focal * y / z, z))

    drawn: list[tuple[float, int, int, int, tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]] = []
    for a, b, c in mesh.faces:
        pa, pb, pc = cam[a], cam[b], cam[c]
        if pa is None or pb is None or pc is None:
            continue
        drawn.append(((pa[2] + pb[2] + pc[2]) / 3.0, a, b, c, pa, pb, pc))
    drawn.sort(key=lambda item: item[0], reverse=True)

    image = Image.new("RGB", (size, size), (214, 216, 220))
    draw = ImageDraw.Draw(image)
    npos = mesh.positions
    for _depth, ia, ib, ic, pa, pb, pc in drawn:
        n = _norm(_cross(_sub(npos[ib], npos[ia]), _sub(npos[ic], npos[ia])))
        shade = max(0.22, min(1.0, 0.35 + 0.75 * abs(_dot(n, light))))
        if mesh.texture is not None and mesh.uvs is not None:
            ua, va = mesh.uvs[ia]
            ub, vb = mesh.uvs[ib]
            uc, vc = mesh.uvs[ic]
            r, g, b = _sample_texture(mesh.texture, (ua + ub + uc) / 3.0, (va + vb + vc) / 3.0)
        elif mesh.colors is not None:
            ca, cb, cc = mesh.colors[ia], mesh.colors[ib], mesh.colors[ic]
            r = int(255 * (ca[0] + cb[0] + cc[0]) / 3.0)
            g = int(255 * (ca[1] + cb[1] + cc[1]) / 3.0)
            b = int(255 * (ca[2] + cb[2] + cc[2]) / 3.0)
        else:
            r = g = b = 180
        color = (
            max(0, min(255, int(r * shade))),
            max(0, min(255, int(g * shade))),
            max(0, min(255, int(b * shade))),
        )
        draw.polygon([(pa[0], pa[1]), (pb[0], pb[1]), (pc[0], pc[1])], fill=color)

    buf = BytesIO()
    image.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
