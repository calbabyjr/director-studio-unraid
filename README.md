# Director Studio for Unraid

Local-first pre-production UI that talks to **your existing [ComfyUI](https://github.com/comfyanonymous/ComfyUI) and [Ollama](https://ollama.com)** containers. This image is an orchestrator only — no GPU, no bundled models.

Upstream application: [ai2764/Director-Studio](https://github.com/ai2764/Director-Studio).

## Install from Community Apps

Once the repository is in the Unraid CA feed:

1. Open **Apps** on Unraid.
2. Search **Director Studio**.
3. Install. Set **App data**, confirm `DS_COMFY_BASE_URL` (`http://127.0.0.1:8188`) and `DS_OLLAMA_BASE_URL` (`http://127.0.0.1:11434`).
4. Start ComfyUI and Ollama first, then start Director Studio.
5. Open `http://TOWER:8790` and pick a Director model in the UI.

Until the listing is approved, add this repo as a **custom template repository** in Community Applications (Apps → Settings → Template Repositories):

```text
https://github.com/calbabyjr/director-studio-unraid
```

Or add the container from Docker → Add Container using the raw template:

```text
https://raw.githubusercontent.com/calbabyjr/director-studio-unraid/main/templates/director-studio.xml
```

## Image

```text
calbabyjr/director-studio:latest
```

Also published as `ghcr.io/calbabyjr/director-studio:latest`.

Host networking is required so `127.0.0.1:8188` and `127.0.0.1:11434` are the Unraid host.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DS_COMFY_BASE_URL` | `http://127.0.0.1:8188` | ComfyUI |
| `DS_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama |
| `DS_VRAM_POLICY` | `shared` | `shared` if Comfy and Ollama use different GPUs; `exclusive` if they share one card |
| `DS_DIRECTOR_NUM_CTX` | `32768` | Ollama context |
| `DS_DIRECTOR_VISION_MODEL` | empty | Optional Ollama tag for Picture inspection |

## Build locally

```bash
cd director-studio-unraid
docker build -t calbabyjr/director-studio:latest -f docker/Dockerfile .
```

## License

Apache-2.0 for this packaging repository. Application code is derived from ai2764/Director-Studio.

## Support

[GitHub Issues](https://github.com/calbabyjr/director-studio-unraid/issues)
