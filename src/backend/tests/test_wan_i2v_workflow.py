from app.pipelines.wan_i2v.workflow import build_graph


def test_wan_graph_animates_the_layout_with_the_uncensored_checkpoints():
    graph, seed = build_graph(
        prompt="She crosses the room and sits.",
        image_name="layout.png",
        high_unet="Wan2.2_Remix_NSFW_i2v_14b_high_lighting_fp8_e4m3fn_v3.0.safetensors",
        low_unet="Wan2.2_Remix_NSFW_i2v_14b_low_lighting_fp8_e4m3fn_v3.0.safetensors",
        clip_name="nsfw_wan_umt5-xxl_fp8_scaled.safetensors",
        vae_name="wan_2.1_vae.safetensors",
        seed=7,
    )

    assert seed == 7
    assert graph["7"]["inputs"]["image"] == "layout.png"
    assert graph["5"]["inputs"]["text"] == "She crosses the room and sits."
    assert graph["1"]["inputs"]["unet_name"].startswith("Wan2.2_Remix_NSFW")
    assert graph["3"]["inputs"]["clip_name"] == "nsfw_wan_umt5-xxl_fp8_scaled.safetensors"
    assert graph["8"]["class_type"] == "WanImageToVideo"
    assert graph["8"]["inputs"]["start_image"] == ["7", 0]
    assert "nsfw" not in graph["6"]["inputs"]["text"].lower()
