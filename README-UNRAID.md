# Director Studio on this Unraid box

Backup of Tower's local checkout, Docker packaging, and Unraid templates.
Upstream: [ai2764/Director-Studio](https://github.com/ai2764/Director-Studio).
Project data (`data/`) is **not** in git.

Local-first pre-production UI from
[ai2764/Director-Studio](https://github.com/ai2764/Director-Studio).
This container does **not** run ComfyUI, Ollama, or CUDA itself. It talks to
the services already on Tower and coordinates exclusive VRAM between them.

| Service | Container | URL | GPU |
| --- | --- | --- | --- |
| Director Studio | `Director-Studio` | http://10.0.1.9:8790 | none (orchestrator) |
| ComfyUI | `ComfyUI-Nvidia-Docker` | http://127.0.0.1:8188 | RTX 3090 |
| Ollama | `ollama` | http://127.0.0.1:11434 | all three cards |

Data lives on the AI SSD: `/mnt/ai/appdata-ai/director-studio/`.

## Start / edit from the Unraid GUI

The running container is owned by Unraid **dockerMan**, not Compose Manager.
On the Docker tab, **Director-Studio** is a clickable name: that opens the
normal Edit form (ports, paths, env). Right-click → Edit works too.

```bash
# rebuild the local image only — then restart from the Docker tab
cd /mnt/ai/appdata-ai/director-studio
docker compose build
```

Do not `docker compose up`. That tags the container as Compose-managed and
hides the Edit button.

Open http://10.0.1.9:8790. Health: http://10.0.1.9:8790/api/health
(`comfy_reachable` and `details.llm.reachable` should both be true).

Pick a Director model in the UI from the Ollama catalog. Good local choices
already pulled: `qwen3:32b`, `qwen3.6:latest`, `qwen3:14b`.

## Why host networking and no GPU on this container

Director Studio's Comfy MCP client uploads files and fetches outputs from
ComfyUI. Host network makes `127.0.0.1:8188` and `127.0.0.1:11434` the same
sockets the other containers already publish.

The app's `exclusive` VRAM policy unloads the Ollama plan model before a
Comfy job (`keep_alive=0`) so the 3090 is free for image/video. Passing a
GPU into Director Studio would only compete with those workers.

To point at a different ComfyUI (GPU1 on `:8190`, 3D on `:8193`), change
`DS_COMFY_BASE_URL` in `docker-compose.yml`.

## ComfyUI extras this box still needs for full pipelines

Verified on `ComfyUI-Nvidia-Docker` (3090):

- Present: `MiniMaxH3ReferenceToVideo`, `TextEncodeQwenImageEditPlus`,
  Qwen Image Edit 2511 weights, MiniMax H3 VAEs and H3 text encoder,
  multi-angle LoRA.
- Missing node: **`CR Prompt List`** (Comfyroll). Scene multi-angle will
  fail until you install
  [ComfyUI_Comfyroll_CustomNodes](https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes)
  into `/mnt/ai/appdata-ai/comfyui-nvidia/basedir/custom_nodes` and restart
  that ComfyUI container.
- Missing weight: workflow asks for
  `minimax_h3_ref2va_pruned_int8_convrot.safetensors`. This box currently
  has `minimax_h3_fl2va_pruned_int8_convrot.safetensors`. Either download
  the Ref2AV unet into `basedir/models/diffusion_models` or import a
  custom H3 workflow in Settings → Workflows → H3 that already runs in
  this ComfyUI.

## Optional: Harness agent

Linux default here is `DS_DIRECTOR_AGENT_RUNTIME=legacy` (same as upstream
Linux portable). The image also contains the Harness sidecar. To use it:

```yaml
DS_DIRECTOR_AGENT_RUNTIME: harness
```

then `docker compose up -d`.

## MiniMax cloud H3

Add `DS_H3_MINIMAX_API_KEY` (or `MINIMAX_API_KEY`) to the compose
environment if you want the official API option next to local ComfyUI.
