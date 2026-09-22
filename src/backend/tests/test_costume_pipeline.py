from __future__ import annotations

from app.core.schemas import JobRecord, JobStatus
from app.pipelines.prop.workflow import NODE_REF_IMAGE_1, NODE_SAVE


def test_costume_pipeline_id_and_kind():
    from app.pipelines import get_pipeline

    pipe = get_pipeline("costume")
    assert pipe.id == "costume"
    assert pipe.asset_kind == "costumes"
    assert pipe.display_name
    assert pipe.library_input_keys() == ["costume"]
    assert "master" in pipe.output_labels


def test_costume_build_prompt_reuses_prop_graph():
    from app.pipelines import get_pipeline

    pipe = get_pipeline("costume")
    job = JobRecord(
        id="job_cos1",
        pipeline_id="costume",
        asset_kind="costumes",
        status=JobStatus.queued,
        name="Red dress",
        notes="silk",
        seed=3,
        created_at="t",
        updated_at="t",
    )
    graph, seed = pipe.build_prompt(job, uploaded_images={"costume": "dress.png"})
    assert seed == 3
    assert graph[NODE_REF_IMAGE_1]["inputs"]["image"] == "dress.png"
    assert graph[NODE_SAVE]["class_type"] == "SaveImage"


def test_generate_costume_requires_name_and_image(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import create_app

    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "jobs_dir", tmp_path / "jobs")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    (tmp_path / "projects").mkdir()
    (tmp_path / "jobs").mkdir()
    (tmp_path / "library").mkdir()

    client = TestClient(create_app())
    missing_image = client.post("/api/costumes/generate", data={"name": "Dress"})
    assert missing_image.status_code == 400
    assert "costume_image" in missing_image.text

    missing_name = client.post(
        "/api/costumes/generate",
        data={"name": "  "},
        files={"costume_image": ("dress.png", b"fake-png-bytes" * 40, "image/png")},
    )
    assert missing_name.status_code == 400
