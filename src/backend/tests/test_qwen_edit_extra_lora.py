from app.config import settings
from app.pipelines.base import stack_qwen_edit_extra_lora


def test_extra_lora_is_inserted_after_lightning_and_rewires_consumers(monkeypatch):
    monkeypatch.setattr(settings, "qwen_edit_extra_lora", "nsfw.safetensors")
    monkeypatch.setattr(settings, "qwen_edit_extra_lora_strength", 0.9)
    prompt = {"5": {"class_type": "LoraLoaderModelOnly", "inputs": {}},
              "6": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["5", 0]}}}
    stack_qwen_edit_extra_lora(prompt, after="5", node_id="90", consumers=[("6", "model")])
    assert prompt["90"]["inputs"] == {"model": ["5", 0], "lora_name": "nsfw.safetensors", "strength_model": 0.9}
    assert prompt["6"]["inputs"]["model"] == ["90", 0]


def test_extra_lora_disabled_leaves_graph_untouched(monkeypatch):
    monkeypatch.setattr(settings, "qwen_edit_extra_lora", "")
    prompt = {"5": {"inputs": {}}, "6": {"inputs": {"model": ["5", 0]}}}
    stack_qwen_edit_extra_lora(prompt, after="5", node_id="90", consumers=[("6", "model")])
    assert "90" not in prompt and prompt["6"]["inputs"]["model"] == ["5", 0]
