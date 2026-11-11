/**
 * App navigation — ordered as a production pipeline.
 * `comingSoon: true` shows a disabled nav chip without a page.
 */
export type NavId = "assets" | "director" | "production";
/** Settings and Director setup sit outside the numbered project stages. */
export type DesktopPage = NavId | "settings" | "director-setup";

export interface NavItem {
  id: NavId;
  label: string;
  step: string;
  /** Tooltip only. Kept out of the accessible name. */
  hint: string;
}

export const NAV_ITEMS: NavItem[] = [
  { id: "director", label: "Director", step: "01", hint: "Plan the story and the shots" },
  { id: "assets", label: "Assets", step: "02", hint: "Cast actors, places, props, and voices" },
  { id: "production", label: "Production", step: "03", hint: "Render the shots" },
];
