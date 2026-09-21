"""Convert ComfyUI canvas (UI) workflows into API prompt graphs."""

from __future__ import annotations

import json

from app.workflow_profiles.h3.inspector import inspect_h3_workflow
from app.workflow_profiles.h3.ui_to_api import (
    looks_like_ui_graph,
    normalize_comfy_workflow,
)


def ui_ref2va_graph() -> dict[str, object]:
    return {
        "last_link_id": 3,
        "last_node_id": 5,
        "nodes": [
            {
                "id": 1,
                "type": "LoadImage",
                "mode": 0,
                "widgets_values": ["hero.png", "image"],
                "inputs": [
                    {
                        "name": "image",
                        "type": "COMBO",
                        "widget": {"name": "image"},
                    },
                    {
                        "name": "upload",
                        "type": "IMAGEUPLOAD",
                        "widget": {"name": "upload"},
                    },
                ],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [1]}],
            },
            {
                "id": 2,
                "type": "SetNode",
                "mode": 0,
                "widgets_values": ["Image 1"],
                "inputs": [{"name": "IMAGE", "type": "IMAGE", "link": 1}],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": []}],
            },
            {
                "id": 3,
                "type": "GetNode",
                "mode": 0,
                "widgets_values": ["Image 1"],
                "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [2]}],
            },
            {
                "id": 4,
                "type": "MiniMaxH3ReferenceToVideo",
                "title": "H3 Main Generator",
                "mode": 0,
                "widgets_values": ["a prompt", 864, 480, 56, "match"],
                "inputs": [
                    {"name": "clip", "type": "CLIP"},
                    {"name": "vae", "type": "VAE"},
                    {"name": "audio_vae", "type": "VAE"},
                    {
                        "name": "prompt",
                        "type": "STRING",
                        "widget": {"name": "prompt"},
                    },
                    {
                        "name": "width",
                        "type": "INT",
                        "widget": {"name": "width"},
                    },
                    {
                        "name": "height",
                        "type": "INT",
                        "widget": {"name": "height"},
                    },
                    {
                        "name": "length",
                        "type": "INT",
                        "widget": {"name": "length"},
                    },
                    {
                        "name": "ref_image_size",
                        "type": "COMBO",
                        "widget": {"name": "ref_image_size"},
                    },
                    {
                        "name": "ref_images.ref_image_0",
                        "type": "IMAGE",
                        "link": 2,
                    },
                ],
                "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [3]}],
            },
            {
                "id": 5,
                "type": "SaveVideo",
                "title": "Final video",
                "mode": 0,
                "widgets_values": {"filename_prefix": "h3", "videopreview": {"hidden": True}},
                "inputs": [{"name": "video", "type": "VIDEO", "link": 3}],
                "outputs": [],
            },
            {
                "id": 6,
                "type": "Reroute",
                "mode": 0,
                "inputs": [{"name": "", "type": "*"}],
                "outputs": [{"name": "", "type": "*"}],
            },
        ],
        "links": [
            [1, 1, 0, 2, 0, "IMAGE"],
            [2, 3, 0, 4, 8, "IMAGE"],
            [3, 4, 0, 5, 0, "VIDEO"],
        ],
        "groups": [],
        "extra": {},
        "config": {},
        "version": 0.4,
        "id": "eee7ca4f-9198-48dd-b48a-80b3f7191873",
        "revision": 0,
    }


OBJECT_INFO = {
    "LoadImage": {
        "display_name": "Load Image",
        "output": ["IMAGE", "MASK"],
        "output_node": False,
        "input": {"required": {"image": ["COMBO", {}]}},
    },
    "MiniMaxH3ReferenceToVideo": {
        "display_name": "MiniMax H3 Ref2AV",
        "output": ["CONDITIONING"],
        "output_node": False,
        "input": {
            "required": {
                "clip": ["CLIP", {}],
                "vae": ["VAE", {}],
                "audio_vae": ["VAE", {}],
                "prompt": ["STRING", {}],
                "width": ["INT", {}],
                "height": ["INT", {}],
                "length": ["INT", {}],
                "ref_image_size": ["COMBO", {}],
            },
            "optional": {
                "ref_images": ["COMFY_AUTOGROW_V3", {}],
            },
        },
    },
    "SaveVideo": {
        "display_name": "Save Video",
        "output": ["VIDEO"],
        "output_node": True,
        "input": {"required": {"filename_prefix": ["STRING", {}]}},
    },
}


def test_detects_canvas_save_with_last_link_id() -> None:
    assert looks_like_ui_graph(ui_ref2va_graph()) is True
    assert looks_like_ui_graph({"1": {"class_type": "X", "inputs": {}}}) is False


def test_converts_set_get_and_drops_upload_widgets() -> None:
    api = normalize_comfy_workflow(ui_ref2va_graph(), object_info=OBJECT_INFO)

    assert "2" not in api
    assert "3" not in api
    assert "6" not in api
    assert api["1"]["class_type"] == "LoadImage"
    assert api["1"]["inputs"] == {"image": "hero.png"}
    assert "upload" not in api["1"]["inputs"]
    h3 = api["4"]
    assert h3["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert h3["inputs"]["prompt"] == "a prompt"
    assert h3["inputs"]["width"] == 864
    assert h3["inputs"]["length"] == 56
    assert h3["inputs"]["ref_images.ref_image_0"] == ["1", 0]
    assert api["5"]["class_type"] == "SaveVideo"
    assert api["5"]["inputs"]["video"] == ["4", 0]
    assert "videopreview" not in api["5"]["inputs"]


def test_prompt_wrapper_unwraps_api_graph() -> None:
    wrapped = {"prompt": {"9": {"class_type": "SaveVideo", "inputs": {}}}, "workflow": ui_ref2va_graph()}
    api = normalize_comfy_workflow(wrapped)
    assert api == {"9": {"class_type": "SaveVideo", "inputs": {}}}


def test_api_graph_is_unchanged() -> None:
    graph = {"136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": ""}}}
    assert normalize_comfy_workflow(graph)["136"]["class_type"] == "MiniMaxH3ReferenceToVideo"


def test_strips_sageattention_patch_from_api_graph() -> None:
    graph = {
        "192": {"class_type": "UNETLoader", "inputs": {}},
        "58": {
            "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "inputs": {"model": ["192", 0]},
        },
        "53": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["58", 0]},
        },
    }
    api = normalize_comfy_workflow(graph)
    assert "58" not in api
    assert api["53"]["inputs"]["model"] == ["192", 0]


def test_inspector_accepts_canvas_save() -> None:
    analysis = inspect_h3_workflow(ui_ref2va_graph(), object_info=OBJECT_INFO)

    assert {issue.code for issue in analysis.issues} == set()
    assert [item.node_id for item in analysis.output_candidates] == ["5"]

    mapped = inspect_h3_workflow(
        ui_ref2va_graph(), object_info=OBJECT_INFO, output_node_id="5"
    )
    assert mapped.mapping is not None
    assert mapped.mapping.inputs.h3_node_id == "4"
    assert mapped.mapping.output.node_id == "5"


def test_inlines_primitive_width() -> None:
    graph = ui_ref2va_graph()
    nodes = graph["nodes"]
    assert isinstance(nodes, list)
    nodes.append(
        {
            "id": 7,
            "type": "PrimitiveInt",
            "mode": 0,
            "widgets_values": [1280, "fixed"],
            "outputs": [{"name": "INT", "type": "INT", "links": [4]}],
        }
    )
    h3 = next(node for node in nodes if node["id"] == 4)
    h3["inputs"][4]["link"] = 4
    graph["links"].append([4, 7, 0, 4, 4, "INT"])

    api = normalize_comfy_workflow(graph)
    assert api["4"]["inputs"]["width"] == 1280
    assert "7" not in api
