import type { LayoutReference } from "./api/types";

export function isRetiredLayout(layout: LayoutReference): boolean {
  return layout.review_status === "reject" || Boolean(layout.superseded_by);
}

export function isDisplayableLayout(layout: LayoutReference): boolean {
  return layout.job_status !== "failed" && layout.job_status !== "cancelled";
}

export function isShotBasis(
  shot: { layout_asset_id: string | null },
  layout: LayoutReference,
): boolean {
  return Boolean(layout.asset_id) && layout.asset_id === shot.layout_asset_id;
}

/** A generated study the user can choose as the shot's basis. */
export function canBaseShotOn(layout: LayoutReference): boolean {
  if (!layout.asset_id || isRetiredLayout(layout)) return false;
  if (layout.job_status === "failed" || layout.job_status === "cancelled") return false;
  return layout.review_status === "usable" || layout.review_status === "pending_review";
}
