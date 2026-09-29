import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, errorMessage } from "./api";
import type { ProjectSummary } from "./types";

type ProjectsContextValue = {
  projects: ProjectSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  removeProject: (id: string) => Promise<void>;
  /** Merge a freshly fetched detail record back into the shared list. */
  upsert: (project: ProjectSummary) => void;
};

const ProjectsContext = createContext<ProjectsContextValue | null>(null);

export function ProjectsProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listProjects();
      setProjects(Array.isArray(data.projects) ? data.projects : []);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const removeProject = useCallback(async (id: string) => {
    await api.deleteProject(id);
    setProjects((current) => current.filter((project) => project.id !== id));
  }, []);

  const upsert = useCallback((project: ProjectSummary) => {
    setProjects((current) => {
      const index = current.findIndex((item) => item.id === project.id);
      if (index === -1) return [project, ...current];
      const next = current.slice();
      next[index] = { ...next[index], ...project };
      return next;
    });
  }, []);

  const value = useMemo<ProjectsContextValue>(
    () => ({ projects, loading, error, refresh, removeProject, upsert }),
    [projects, loading, error, refresh, removeProject, upsert],
  );

  return <ProjectsContext.Provider value={value}>{children}</ProjectsContext.Provider>;
}

export function useProjects(): ProjectsContextValue {
  const context = useContext(ProjectsContext);
  if (!context) throw new Error("useProjects 必须在 ProjectsProvider 内使用。");
  return context;
}
