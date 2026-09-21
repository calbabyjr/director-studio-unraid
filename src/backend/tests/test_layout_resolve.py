from app.core.projects.layouts import LayoutReference, resolve_layout_reference
from app.core.projects.models import Shot, ShotStatus


def _shot(*layouts: LayoutReference) -> Shot:
    return Shot(
        id="sht_resolve",
        project_id="prj_resolve",
        scene_id="sc01",
        title="Resolve",
        script_beat="beat",
        duration_s=6.0,
        status=ShotStatus.needs_review,
        layout_refs=list(layouts),
    )


def test_resolve_layout_reference_accepts_library_asset_id():
    layout = LayoutReference(
        id="lref_1fc6ed17bdd8",
        asset_id="lay_0ece40bc9a8a",
        job_id="job_0c4276e4677a",
        purpose="blocking",
        review_status="pending_review",
    )
    shot = _shot(layout)
    assert resolve_layout_reference(shot, "lay_0ece40bc9a8a").id == layout.id
    assert resolve_layout_reference(shot, layout.id).id == layout.id
    assert resolve_layout_reference(
        shot,
        "/api/files/library/layouts/lay_0ece40bc9a8a/layout.png",
    ).id == layout.id


def test_resolve_layout_reference_prefers_live_pending_when_asset_repeats():
    old = LayoutReference(
        id="lref_old",
        asset_id="lay_shared",
        purpose="old",
        review_status="reject",
        superseded_by="lref_new",
        created_at="2026-01-01T00:00:00+00:00",
    )
    new = LayoutReference(
        id="lref_new",
        asset_id="lay_shared",
        purpose="new",
        review_status="pending_review",
        created_at="2026-01-02T00:00:00+00:00",
    )
    shot = _shot(old, new)
    assert resolve_layout_reference(shot, "lay_shared").id == "lref_new"
