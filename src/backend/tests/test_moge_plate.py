from __future__ import annotations

import asyncio

import pytest

from app.pipelines.moge_plate.workflow import (
    NODE_DEPTH,
    NODE_INFER,
    NODE_LOAD,
    NODE_MODEL,
    NODE_NORMAL,
    NODE_SAVE_DEPTH,
    NODE_SAVE_NORMAL,
    build_moge_plate_graph,
    map_history_outputs,
)
from app.core.schemas import ComfyImageRef, JobRecord, JobStatus


def test_moge_plate_pipeline_id():
    from app.pipelines import get_pipeline

    pipe = get_pipeline("moge_plate")
    assert pipe.id == "moge_plate"
    assert pipe.asset_kind == "scenes"
    assert pipe.library_input_keys() == ["scene"]


def test_moge_plate_graph_node_types():
    graph = build_moge_plate_graph("plate.png", job_id="job_moge1")
    types = {node["class_type"] for node in graph.values()}
    assert types == {
        "LoadImage",
        "LoadMoGeModel",
        "MoGeInference",
        "MoGeRender",
        "SaveImage",
    }
    assert graph[NODE_LOAD]["inputs"]["image"] == "plate.png"
    assert graph[NODE_MODEL]["inputs"]["model_name"] == (
        "moge_2_vitl_normal_fp16.safetensors"
    )
    assert graph[NODE_INFER]["class_type"] == "MoGeInference"
    assert graph[NODE_INFER]["inputs"]["moge_model"] == [NODE_MODEL, 0]
    assert graph[NODE_DEPTH]["inputs"]["output"] == "depth_colored"
    assert graph[NODE_NORMAL]["inputs"]["output"] == "normal_opengl"
    assert graph[NODE_SAVE_DEPTH]["class_type"] == "SaveImage"
    assert graph[NODE_SAVE_NORMAL]["class_type"] == "SaveImage"
    assert "job_moge1" in graph[NODE_SAVE_DEPTH]["inputs"]["filename_prefix"]


def test_moge_plate_pipeline_build_prompt_uses_scene_plate():
    from app.pipelines import get_pipeline

    pipe = get_pipeline("moge_plate")
    job = JobRecord(
        id="job_moge_build",
        pipeline_id="moge_plate",
        asset_kind="scenes",
        status=JobStatus.queued,
        name="moge:Room",
        created_at="t",
        updated_at="t",
    )
    graph, seed = pipe.build_prompt(job, uploaded_images={"scene": "still.png"})
    assert seed == 0
    assert graph[NODE_LOAD]["inputs"]["image"] == "still.png"


def test_moge_from_plate_form_false_string_skips_moge_pipeline(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.jobs import store
    from app.main import create_app
    from app.pipelines.scene import router as scene_router

    started: list[str] = []

    async def fake_start(job, *, images=None):
        started.append(job.pipeline_id)
        return job

    monkeypatch.setattr(scene_router, "start_pipeline_job", fake_start)
    client = TestClient(create_app())
    response = client.post(
        "/api/scenes/generate",
        data={
            "name": "Room",
            "moge_from_plate": "false",
            "project_id": "",
        },
        files={"scene_image": ("plate.png", b"\x89PNG\r\n" + b"x" * 80, "image/png")},
    )
    assert response.status_code == 200, response.text
    assert started == ["scene"]
    job = store.load_job(response.json()["id"])
    assert job is not None
    assert job.params.get("moge_from_plate") is False


def test_moge_from_plate_form_true_string_starts_scene_job_without_waiting(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.jobs import store
    from app.main import create_app
    from app.pipelines.scene import router as scene_router

    started: list[str] = []

    async def fake_start(job, *, images=None):
        started.append(job.pipeline_id)
        return job.model_copy(update={"status": JobStatus.queued})

    monkeypatch.setattr(scene_router, "start_pipeline_job", fake_start)
    client = TestClient(create_app())
    response = client.post(
        "/api/scenes/generate",
        data={
            "name": "Room",
            "moge_from_plate": "true",
        },
        files={"scene_image": ("plate.png", b"\x89PNG\r\n" + b"x" * 80, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pipeline_id"] == "scene"
    assert body["status"] == "queued"
    assert started == ["scene"]
    job = store.load_job(body["id"])
    assert job is not None
    assert job.params.get("moge_from_plate") is True


@pytest.mark.asyncio
async def test_scene_prepare_run_inputs_runs_moge_then_attaches_views(monkeypatch, tmp_path):
    from app.config import settings
    from app.core.jobs import store
    from app.core.schemas import OutputSlot
    from app.pipelines import get_pipeline

    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setattr(settings, "jobs_dir", jobs_root)

    nested: list[str] = []

    async def fake_nested(job, *, images=None, cancel=None):
        del cancel
        nested.append(job.pipeline_id)
        assert images and "scene" in images
        out = store.job_dir(job.id, project_id=job.project_id) / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        orbit = out / "moge_orbit.png"
        back = out / "moge_back.png"
        orbit.write_bytes(b"orbit")
        back.write_bytes(b"back")
        job.status = JobStatus.succeeded
        job.outputs = {
            "moge_orbit": OutputSlot(
                key="moge_orbit",
                label="MoGe depth",
                filename=orbit.name,
                path=str(orbit),
            ),
            "moge_back": OutputSlot(
                key="moge_back",
                label="MoGe normals",
                filename=back.name,
                path=str(back),
            ),
        }
        store.save_job(job)
        return job

    monkeypatch.setattr(
        "app.core.jobs.runner.run_nested_pipeline_job",
        fake_nested,
    )

    pipe = get_pipeline("scene")
    job = store.create_job(
        pipeline_id="scene",
        asset_kind="scenes",
        name="Room",
        params={"moge_from_plate": True},
    )
    images: dict[str, tuple[str, bytes]] = {"scene": ("plate.png", b"plate")}
    await pipe.prepare_run_inputs(job, images, asyncio.Event())
    assert nested == ["moge_plate"]
    assert images["moge_orbit"][1] == b"orbit"
    assert images["moge_back"][1] == b"back"
    job = store.load_job(job.id) or job
    assert job.params.get("moge_plate_job_id")
    assert job.status == JobStatus.uploading


@pytest.mark.asyncio
async def test_scene_prepare_run_inputs_skips_when_flag_false(monkeypatch):
    from app.pipelines import get_pipeline

    async def boom(*_args, **_kwargs):
        raise AssertionError("MoGe should not run when moge_from_plate is false")

    monkeypatch.setattr("app.core.jobs.runner.run_nested_pipeline_job", boom)
    pipe = get_pipeline("scene")
    job = JobRecord(
        id="job_skip_moge",
        pipeline_id="scene",
        asset_kind="scenes",
        status=JobStatus.queued,
        name="Room",
        created_at="t",
        updated_at="t",
        params={"moge_from_plate": False},
    )
    images: dict[str, tuple[str, bytes]] = {"scene": ("plate.png", b"plate")}
    await pipe.prepare_run_inputs(job, images, asyncio.Event())
    assert set(images) == {"scene"}


@pytest.mark.asyncio
async def test_scene_prepare_run_inputs_raises_when_moge_fails(monkeypatch, tmp_path):
    from app.config import settings
    from app.core.jobs import store
    from app.pipelines import get_pipeline

    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setattr(settings, "jobs_dir", jobs_root)

    async def fake_nested(job, *, images=None, cancel=None):
        del images, cancel
        job.status = JobStatus.failed
        job.error = "no comfy"
        store.save_job(job)
        return job

    monkeypatch.setattr("app.core.jobs.runner.run_nested_pipeline_job", fake_nested)
    pipe = get_pipeline("scene")
    job = store.create_job(
        pipeline_id="scene",
        asset_kind="scenes",
        name="Room",
        params={"moge_from_plate": True},
    )
    images: dict[str, tuple[str, bytes]] = {"scene": ("plate.png", b"plate")}
    with pytest.raises(ValueError, match="MoGe from plate failed"):
        await pipe.prepare_run_inputs(job, images, asyncio.Event())


@pytest.mark.asyncio
async def test_run_job_fails_scene_when_moge_nested_fails(monkeypatch, tmp_path):
    from app.config import settings
    from app.core.jobs import runner, store

    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setattr(settings, "jobs_dir", jobs_root)

    class Rec:
        async def reserve_generation(self, **kwargs):
            return None

        async def release_generation(self, job_id):
            return None

        async def before_comfy_job(self, pipeline_id):
            return None

        async def after_comfy_job(self, pipeline_id, terminal_status):
            return None

        async def update_generation(self, job_id, *, status, phase):
            return None

    monkeypatch.setattr(runner, "get_orchestrator", lambda: Rec())

    async def fake_nested(job, *, images=None, cancel=None):
        del images, cancel
        job.status = JobStatus.failed
        job.error = "no comfy"
        store.save_job(job)
        return job

    monkeypatch.setattr(runner, "run_nested_pipeline_job", fake_nested)
    job = store.create_job(
        pipeline_id="scene",
        asset_kind="scenes",
        name="Room",
        params={"moge_from_plate": True},
    )
    await runner.start_pipeline_job(job, images={"scene": ("plate.png", b"plate")})
    final = await runner.await_pipeline_job(job.id)
    assert final is not None
    assert final.status == JobStatus.failed
    assert "MoGe from plate failed" in (final.error or "")


def test_map_history_outputs_pairs_depth_and_normals():
    mapped = map_history_outputs(
        {
            "outputs": {
                NODE_SAVE_DEPTH: {
                    "images": [
                        {
                            "filename": "depth.png",
                            "subfolder": "",
                            "type": "output",
                        }
                    ]
                },
                NODE_SAVE_NORMAL: {
                    "images": [
                        {
                            "filename": "normal.png",
                            "subfolder": "",
                            "type": "output",
                        }
                    ]
                },
            }
        }
    )
    assert set(mapped) == {"moge_orbit", "moge_back"}
    assert isinstance(mapped["moge_orbit"], ComfyImageRef)
    assert mapped["moge_orbit"].filename == "depth.png"
    assert mapped["moge_back"].filename == "normal.png"
