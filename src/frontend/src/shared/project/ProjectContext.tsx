import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  createProject,
  listProjects,
  updateProject,
  type Project,
} from "../../features/director/api";
import type { ProjectMode } from "../api/types";

const STORAGE_KEY = "ds.activeProjectId";

type ProjectContextValue = {
  projects: Project[];
  projectId: string | null;
  project: Project | null;
  loading: boolean;
  error: string | null;
  setProjectId: (id: string | null) => void;
  refreshProjects: () => Promise<void>;
  createAndSelect: (
    name: string,
    scriptText?: string,
    mode?: ProjectMode,
  ) => Promise<Project>;
  renameProject: (name: string) => Promise<Project>;
};

const ProjectContext = createContext<ProjectContextValue | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectIdState] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshProjects = useCallback(async () => {
    setError(null);
    try {
      const items = await listProjects();
      setProjects(items);
      setProjectIdState((cur) => {
        if (cur && items.some((p) => p.id === cur)) return cur;
        const next = items[0]?.id ?? null;
        try {
          if (next) localStorage.setItem(STORAGE_KEY, next);
          else localStorage.removeItem(STORAGE_KEY);
        } catch {
          /* ignore */
        }
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);

  const setProjectId = useCallback((id: string | null) => {
    setProjectIdState(id);
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const createAndSelect = useCallback(
    async (name: string, scriptText = "", mode: ProjectMode = "director") => {
      const p = await createProject({
        name: name.trim() || "Untitled Project",
        script_text: scriptText,
        mode,
      });
      await refreshProjects();
      setProjectId(p.id);
      return p;
    },
    [refreshProjects, setProjectId],
  );

  const renameProject = useCallback(
    async (name: string) => {
      if (!projectId) {
        throw new Error("No project selected");
      }
      const trimmed = name.trim();
      if (!trimmed) {
        throw new Error("name cannot be empty");
      }
      const renamedId = projectId;
      const updated = await updateProject(renamedId, { name: trimmed });
      setProjects((items) => {
        const present = items.some((p) => p.id === updated.id);
        if (!present) return [updated, ...items];
        return items.map((p) => (p.id === updated.id ? { ...p, ...updated } : p));
      });
      setProjectId(renamedId);
      await refreshProjects();
      setProjectId(renamedId);
      return updated;
    },
    [projectId, refreshProjects, setProjectId],
  );

  const project = useMemo(
    () => projects.find((p) => p.id === projectId) ?? null,
    [projects, projectId],
  );

  const value = useMemo(
    () => ({
      projects,
      projectId,
      project,
      loading,
      error,
      setProjectId,
      refreshProjects,
      createAndSelect,
      renameProject,
    }),
    [
      projects,
      projectId,
      project,
      loading,
      error,
      setProjectId,
      refreshProjects,
      createAndSelect,
      renameProject,
    ],
  );

  return (
    <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
  );
}

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) {
    throw new Error("useProject must be used within ProjectProvider");
  }
  return ctx;
}
