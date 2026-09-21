"""Convert ComfyUI canvas (UI) workflow JSON into an API prompt graph."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

MODE_NEVER = 2
MODE_BYPASS = 4

VIRTUAL_TYPES = {
    "GetNode",
    "SetNode",
    "Reroute",
    "Note",
    "MarkdownNote",
    "PrimitiveNode",
    "PrimitiveInt",
    "PrimitiveFloat",
    "PrimitiveBoolean",
    "PrimitiveString",
}

PRIMITIVE_TYPES = {
    "PrimitiveNode",
    "PrimitiveInt",
    "PrimitiveFloat",
    "PrimitiveBoolean",
    "PrimitiveString",
}

SKIP_WIDGET_NAMES = {
    "upload",
    "choose file to upload",
    "choose video to upload",
    "videopreview",
    "control_after_generate",
}


class UiWorkflowError(ValueError):
    """The uploaded JSON is a canvas workflow that could not be converted."""


def looks_like_ui_graph(data: object) -> bool:
    if not isinstance(data, Mapping):
        return False
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return False
    if "links" in data or "last_node_id" in data or "last_link_id" in data:
        return True
    if not nodes:
        return False
    first = nodes[0]
    return (
        isinstance(first, Mapping)
        and "type" in first
        and "id" in first
        and "class_type" not in first
    )


def looks_like_api_graph(data: object) -> bool:
    if looks_like_ui_graph(data) or not isinstance(data, Mapping) or not data:
        return False
    return any(
        isinstance(node, Mapping) and isinstance(node.get("class_type"), str)
        for node in data.values()
    )


def normalize_comfy_workflow(
    data: object, *, object_info: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return an API prompt graph. UI canvas saves are converted."""
    if not isinstance(data, Mapping):
        raise UiWorkflowError("Workflow JSON must be an object")

    prompt = data.get("prompt")
    if isinstance(prompt, Mapping) and looks_like_api_graph(prompt):
        return _copy_api_graph(prompt)
    if looks_like_ui_graph(data):
        return convert_ui_workflow(data, object_info=object_info)
    if looks_like_api_graph(data):
        return _copy_api_graph(data)
    if any(key in data for key in ("last_link_id", "last_node_id", "groups")):
        raise UiWorkflowError(
            "This is a ComfyUI canvas save (UI graph), not an API prompt. "
            "Director Studio could not convert it because the node list is missing. "
            "In ComfyUI use File → Export (API) and import that JSON."
        )
    return _copy_api_graph(data)


def convert_ui_workflow(
    data: Mapping[str, Any], *, object_info: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise UiWorkflowError(
            "This ComfyUI canvas save has no nodes. "
            "In ComfyUI use File → Export (API) after the graph runs."
        )

    nodes: dict[str, dict[str, Any]] = {}
    for item in raw_nodes:
        if not isinstance(item, Mapping) or item.get("id") is None:
            continue
        if isinstance(item.get("subgraph"), Mapping) or item.get("type") in {
            "Subgraph",
            "SubgraphNode",
        }:
            raise UiWorkflowError(
                "Workflows with subgraphs cannot be imported. "
                "Expand them in ComfyUI or use File → Export (API)."
            )
        nodes[str(item["id"])] = dict(item)

    incoming = _index_incoming(nodes, data.get("links"))
    sets_by_name = _index_sets(nodes)

    api: dict[str, Any] = {}
    for node_id, node in nodes.items():
        if not _keep_node(node):
            continue
        class_type = str(node.get("type") or "")
        inputs = _widget_inputs(node, object_info)
        for input_name, origin in _linked_inputs(node, incoming).items():
            resolved = _resolve_origin(
                origin[0], origin[1], nodes, incoming, sets_by_name
            )
            if resolved is None:
                continue
            kind, source_id, source_slot = resolved
            if kind == "primitive":
                value = _primitive_value(nodes.get(source_id) or {})
                if value is not None:
                    inputs[input_name] = value
                continue
            if source_id not in nodes or not _keep_node(nodes[source_id]):
                continue
            inputs[input_name] = [source_id, source_slot]
        if object_info is not None:
            inputs = _filter_known_inputs(class_type, inputs, object_info)
        api_node: dict[str, Any] = {"class_type": class_type, "inputs": inputs}
        title = node.get("title")
        if isinstance(title, str) and title.strip():
            api_node["_meta"] = {"title": title.strip()[:256]}
        api[node_id] = api_node

    if not api:
        raise UiWorkflowError(
            "This ComfyUI canvas save converted to an empty API graph. "
            "In ComfyUI use File → Export (API) after the workflow runs."
        )
    bypass_model_passthrough_nodes(api, SAGE_PATCH_CLASSES)
    return api


SAGE_PATCH_CLASSES = {"MiniMaxH3MemoryEfficientSageAttentionPatch"}


def bypass_model_passthrough_nodes(
    graph: dict[str, Any], class_types: set[str]
) -> None:
    """Rewire consumers around optional model-in/model-out patches."""
    for node_id in list(graph):
        node = graph.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") not in class_types:
            continue
        source = (node.get("inputs") or {}).get("model")
        if not (
            isinstance(source, list)
            and len(source) == 2
            and isinstance(source[0], (str, int))
            and isinstance(source[1], int)
        ):
            continue
        replacement = [str(source[0]), source[1]]
        for consumer in graph.values():
            if not isinstance(consumer, dict):
                continue
            consumer_inputs = consumer.get("inputs") or {}
            for input_name, value in list(consumer_inputs.items()):
                if (
                    isinstance(value, list)
                    and len(value) >= 2
                    and str(value[0]) == str(node_id)
                ):
                    consumer_inputs[input_name] = replacement
        del graph[node_id]


def _copy_api_graph(data: Mapping[str, Any]) -> dict[str, Any]:
    graph = {str(node_id): copy.deepcopy(node) for node_id, node in data.items()}
    bypass_model_passthrough_nodes(graph, SAGE_PATCH_CLASSES)
    return graph


def _keep_node(node: Mapping[str, Any]) -> bool:
    class_type = str(node.get("type") or "")
    if not class_type or class_type in VIRTUAL_TYPES:
        return False
    mode = int(node.get("mode") or 0)
    if mode in {MODE_NEVER, MODE_BYPASS}:
        return False
    flags = node.get("flags")
    if isinstance(flags, Mapping) and flags.get("disabled"):
        return False
    return True


def _set_get_name(node: Mapping[str, Any]) -> str:
    values = node.get("widgets_values")
    if isinstance(values, list) and values:
        name = values[0]
        return str(name) if name is not None else ""
    if isinstance(values, Mapping):
        for key in ("value", "name", "constant"):
            if key in values and values[key] is not None:
                return str(values[key])
        for value in values.values():
            if value is not None and not isinstance(value, (dict, list)):
                return str(value)
    return ""


def _primitive_value(node: Mapping[str, Any]) -> object:
    values = node.get("widgets_values")
    if isinstance(values, list) and values:
        return values[0]
    if isinstance(values, Mapping):
        if "value" in values:
            return values["value"]
        for value in values.values():
            if not isinstance(value, (dict, list)):
                return value
    return None


def _index_sets(nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    by_name: dict[str, str] = {}
    for node_id, node in nodes.items():
        if node.get("type") != "SetNode":
            continue
        if int(node.get("mode") or 0) == MODE_NEVER:
            continue
        name = _set_get_name(node)
        if not name:
            continue
        existing = by_name.get(name)
        if existing is None or int(nodes[existing].get("mode") or 0) == MODE_BYPASS:
            by_name[name] = node_id
    return by_name


def _parse_link(link: object) -> tuple[object, str, int, str, int] | None:
    if isinstance(link, Mapping):
        try:
            return (
                link.get("id"),
                str(link["origin_id"]),
                int(link["origin_slot"]),
                str(link["target_id"]),
                int(link["target_slot"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(link, Sequence) and not isinstance(link, (str, bytes)) and len(link) >= 5:
        try:
            return (
                link[0],
                str(link[1]),
                int(link[2]),
                str(link[3]),
                int(link[4]),
            )
        except (TypeError, ValueError):
            return None
    return None


def _index_incoming(
    nodes: Mapping[str, Mapping[str, Any]], links_raw: object
) -> dict[tuple[str, int], tuple[str, int]]:
    incoming: dict[tuple[str, int], tuple[str, int]] = {}
    links_by_id: dict[object, tuple[str, int, str, int]] = {}
    if isinstance(links_raw, Mapping):
        items = links_raw.values()
    elif isinstance(links_raw, list):
        items = links_raw
    else:
        items = []
    for item in items:
        parsed = _parse_link(item)
        if parsed is None:
            continue
        link_id, src, src_slot, dst, dst_slot = parsed
        links_by_id[link_id] = (src, src_slot, dst, dst_slot)
        incoming[(dst, dst_slot)] = (src, src_slot)

    for node_id, node in nodes.items():
        inputs = node.get("inputs")
        if not isinstance(inputs, list):
            continue
        for slot, spec in enumerate(inputs):
            if not isinstance(spec, Mapping):
                continue
            link_id = spec.get("link")
            if link_id is None:
                continue
            if link_id in links_by_id:
                src, src_slot, _dst, _dst_slot = links_by_id[link_id]
                incoming[(node_id, slot)] = (src, src_slot)
    return incoming


def _linked_inputs(
    node: Mapping[str, Any], incoming: Mapping[tuple[str, int], tuple[str, int]]
) -> dict[str, tuple[str, int]]:
    result: dict[str, tuple[str, int]] = {}
    node_id = str(node["id"])
    inputs = node.get("inputs")
    if not isinstance(inputs, list):
        return result
    for slot, spec in enumerate(inputs):
        if not isinstance(spec, Mapping):
            continue
        name = spec.get("name")
        if not isinstance(name, str) or not name:
            continue
        origin = incoming.get((node_id, slot))
        if origin is not None:
            result[name] = origin
    return result


def _widget_inputs(
    node: Mapping[str, Any], object_info: Mapping[str, Any] | None
) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    values = node.get("widgets_values")
    names = _widget_names(node)
    known = _known_input_names(str(node.get("type") or ""), object_info)

    if isinstance(values, Mapping):
        for name, value in values.items():
            if not isinstance(name, str) or name in SKIP_WIDGET_NAMES:
                continue
            if known is not None and name not in known:
                continue
            if isinstance(value, dict):
                continue
            inputs[name] = value
        return inputs

    if isinstance(values, list):
        for name, value in zip(names, values):
            if name in SKIP_WIDGET_NAMES:
                continue
            if known is not None and name not in known:
                continue
            inputs[name] = value
    return inputs


def _widget_names(node: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for spec in node.get("inputs") or []:
        if not isinstance(spec, Mapping):
            continue
        widget = spec.get("widget")
        if isinstance(widget, Mapping) and isinstance(widget.get("name"), str):
            names.append(widget["name"])
        elif widget and isinstance(spec.get("name"), str):
            names.append(str(spec["name"]))
    return names


def _known_input_names(
    class_type: str, object_info: Mapping[str, Any] | None
) -> set[str] | None:
    if object_info is None or class_type not in object_info:
        return None
    metadata = object_info.get(class_type)
    if not isinstance(metadata, Mapping):
        return None
    payload = metadata.get("input")
    if not isinstance(payload, Mapping):
        return None
    names: set[str] = set()
    autogrow: set[str] = set()
    for section in ("required", "optional", "hidden"):
        group = payload.get(section)
        if not isinstance(group, Mapping):
            continue
        for name, spec in group.items():
            names.add(str(name))
            if (
                isinstance(spec, list)
                and spec
                and isinstance(spec[0], str)
                and spec[0].startswith("COMFY_AUTOGROW")
            ):
                autogrow.add(str(name))
    if autogrow:
        names.update(autogrow)
    return names


def _is_api_link(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and not isinstance(value[0], bool)
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
        and value[1] >= 0
    )


def _filter_known_inputs(
    class_type: str, inputs: dict[str, Any], object_info: Mapping[str, Any]
) -> dict[str, Any]:
    known = _known_input_names(class_type, object_info)
    if known is None:
        return {key: value for key, value in inputs.items() if key not in SKIP_WIDGET_NAMES}
    filtered: dict[str, Any] = {}
    for key, value in inputs.items():
        if key in SKIP_WIDGET_NAMES:
            continue
        if _is_api_link(value):
            filtered[key] = value
            continue
        if key in known or any(key.startswith(f"{parent}.") for parent in known):
            filtered[key] = value
    return filtered


def _resolve_origin(
    node_id: str,
    slot: int,
    nodes: Mapping[str, Mapping[str, Any]],
    incoming: Mapping[tuple[str, int], tuple[str, int]],
    sets_by_name: Mapping[str, str],
    *,
    seen: set[str] | None = None,
) -> tuple[str, str, int] | None:
    seen = seen or set()
    if node_id in seen or node_id not in nodes:
        return None
    seen.add(node_id)
    node = nodes[node_id]
    class_type = str(node.get("type") or "")
    mode = int(node.get("mode") or 0)

    if mode == MODE_NEVER:
        return None

    if class_type == "GetNode":
        setter_id = sets_by_name.get(_set_get_name(node))
        if setter_id is None:
            return None
        origin = incoming.get((setter_id, 0))
        if origin is None:
            return None
        return _resolve_origin(
            origin[0], origin[1], nodes, incoming, sets_by_name, seen=seen
        )

    if class_type == "SetNode" or class_type == "Reroute" or mode == MODE_BYPASS:
        in_slot = 0 if class_type in {"SetNode", "Reroute"} else slot
        origin = incoming.get((node_id, in_slot))
        if origin is None:
            return None
        return _resolve_origin(
            origin[0], origin[1], nodes, incoming, sets_by_name, seen=seen
        )

    if class_type in PRIMITIVE_TYPES:
        return ("primitive", node_id, 0)

    if not _keep_node(node):
        return None
    return ("node", node_id, slot)


__all__ = [
    "UiWorkflowError",
    "convert_ui_workflow",
    "looks_like_api_graph",
    "looks_like_ui_graph",
    "normalize_comfy_workflow",
]
