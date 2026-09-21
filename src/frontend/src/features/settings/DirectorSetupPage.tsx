import { PageShell } from "../../shared/components/PageShell";
import { DirectorSoulSetup } from "./DirectorSoulSetup";

export function DirectorSetupPage({
  onClose,
}: {
  onClose?: () => void;
}) {
  return (
    <PageShell
      title="Director setup"
      subtitle="Create and edit directing souls here. You do not need a project open."
      className="director-setup-page"
      actions={onClose ? (
        <button
          type="button"
          className="settings-close-button"
          aria-label="Close Director setup"
          title="Close Director setup"
          onClick={onClose}
        >
          ×
        </button>
      ) : null}
    >
      <DirectorSoulSetup />
    </PageShell>
  );
}
