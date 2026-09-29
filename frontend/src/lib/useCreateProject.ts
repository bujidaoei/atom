import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "./api";

type CreateProjectResult = {
  create: (prompt: string) => Promise<void>;
  submitting: boolean;
  error: string | null;
  clearError: () => void;
};

/**
 * Creates a `draft` project and hands off to the workspace, which starts the
 * planning run itself so the SSE stream is attached before Mike speaks.
 */
export function useCreateProject(onCreated?: () => void): CreateProjectResult {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const create = useCallback(
    async (prompt: string) => {
      const trimmed = prompt.trim();
      if (!trimmed || submitting) return;
      setSubmitting(true);
      setError(null);
      try {
        const { project } = await api.createProject(trimmed);
        onCreated?.();
        navigate(`/app/p/${project.id}`);
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setSubmitting(false);
      }
    },
    [navigate, onCreated, submitting],
  );

  return { create, submitting, error, clearError: () => setError(null) };
}
