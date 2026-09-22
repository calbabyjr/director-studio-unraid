import { PageShell } from "../../shared/components/PageShell";
import { DirectorSoulSetup } from "./DirectorSoulSetup";
import { WorkspaceFilesSetup } from "./WorkspaceFilesSetup";

export function DirectorSetupPage({
  onClose,
}: {
  onClose?: () => void;
}) {
  return (
    <PageShell
      title="Director setup"
      subtitle="Each director has its own files. You do not need a project open to edit souls."
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
      <WorkspaceFilesSetup scope="project" />
    </PageShell>
  );
}
