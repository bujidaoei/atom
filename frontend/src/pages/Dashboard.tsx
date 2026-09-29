import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AgentRow } from "../components/AgentRow";
import { Composer } from "../components/Composer";
import { Button, IconButton } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import { StatusBadge } from "../components/ui/Badge";
import { EmptyState, ErrorState, Skeleton } from "../components/ui/States";
import { takePendingPrompt, useAuth } from "../lib/auth";
import { errorMessage } from "../lib/api";
import { EXAMPLE_PROMPTS } from "../lib/examples";
import { formatRelative } from "../lib/format";
import { useProjects } from "../lib/projects";
import type { ProjectSummary } from "../lib/types";
import { useCreateProject } from "../lib/useCreateProject";

export function DashboardPage() {
  const { user } = useAuth();
  const { projects, loading, error, refresh, removeProject } = useProjects();
  const [prompt, setPrompt] = useState("");
  const [carriedOver, setCarriedOver] = useState(false);
  const { create, submitting, error: createError } = useCreateProject(refresh);

  // A prompt typed on the landing page while signed out lands here after auth.
  useEffect(() => {
    const pending = takePendingPrompt();
    if (pending) {
      setPrompt(pending);
      setCarriedOver(true);
    }
  }, []);

  const outOfCredits = user !== null && user.credits <= 0;

  return (
    <div className="mx-auto flex max-w-[1000px] flex-col px-l py-xxl">
      <AgentRow size="lg" className="mb-l" />

      <h1 className="text-center text-h1 font-medium tracking-[-0.01em] text-neutral-95">
        你今天想创造什么？
      </h1>

      <div className="mx-auto mt-xl w-full max-w-[720px]">
        <Composer
          value={prompt}
          onChange={(next) => {
            setPrompt(next);
            setCarriedOver(false);
          }}
          onSubmit={() => void create(prompt)}
          submitting={submitting}
          error={createError}
          disabled={outOfCredits}
          disabledReason="额度已用完，无法开始新的构建。"
          submitLabel="开始构建"
          meta={
            carriedOver ? (
              <span className="text-brand-text">已带回你在首页写的想法</span>
            ) : undefined
          }
        />

        <div className="mt-m flex flex-wrap items-center gap-xs">
          <span className="text-sm text-neutral-40">试试：</span>
          {EXAMPLE_PROMPTS.slice(0, 4).map((example) => (
            <button
              key={example.title}
              type="button"
              onClick={() => {
                setPrompt(example.prompt);
                setCarriedOver(false);
              }}
              className="hairline rounded-full border-neutral-12 bg-base-tertiary px-m py-[3px] text-sm text-neutral-80 transition-colors duration-ui ease-ui hover:border-neutral-20 hover:text-neutral-95 active:bg-base-secondary-alt"
            >
              {example.title}
            </button>
          ))}
        </div>
      </div>

      <section className="mt-xxxl">
        <div className="flex items-baseline justify-between gap-m">
          <h2 className="text-lg font-medium text-neutral-95">你的项目</h2>
          {projects.length > 0 ? (
            <span className="text-sm text-neutral-60">{projects.length} 个</span>
          ) : null}
        </div>

        <div className="mt-l">
          {loading ? (
            <div className="grid grid-cols-1 gap-m sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((index) => (
                <Skeleton key={index} className="h-[124px] w-full" />
              ))}
            </div>
          ) : error ? (
            <ErrorState message={error} onRetry={() => void refresh()} />
          ) : projects.length === 0 ? (
            <div className="hairline rounded-xl border-dashed border-neutral-20 bg-base-tertiary">
              <EmptyState
                title="还没有项目"
                description="在上面写一句想法，Mike 会先把它拆成计划，然后整个 squad 接力往下走。"
              />
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-m sm:grid-cols-2 lg:grid-cols-3">
              {projects.map((project) => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  onDelete={() => removeProject(project.id)}
                />
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function ProjectCard({
  project,
  onDelete,
}: {
  project: ProjectSummary;
  onDelete: () => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  return (
    <div className="hairline group relative flex flex-col gap-s rounded-l border-neutral-12 bg-base-tertiary p-l transition-[border-color,box-shadow,transform] duration-ui ease-ui hover:-translate-y-[2px] hover:border-neutral-20 hover:shadow-flat focus-within:border-neutral-20">
      <div className="flex items-start justify-between gap-s">
        <Link
          to={`/app/p/${project.id}`}
          className="min-w-0 flex-1 rounded-m text-md font-medium leading-5 text-neutral-95 hover:text-brand-text"
        >
          <span className="line-clamp-2">{project.title}</span>
        </Link>
        <IconButton
          label="删除项目"
          onClick={() => setConfirming(true)}
          className="opacity-0 transition-opacity duration-ui ease-ui group-hover:opacity-100 focus-visible:opacity-100"
        >
          <Icon name="trash" size={14} />
        </IconButton>
      </div>

      <p className="line-clamp-2 min-h-[36px] text-sm leading-[18px] text-neutral-60">
        {project.summary ?? "还没有摘要，规划完成后 Emma 会补上。"}
      </p>

      <div className="mt-auto flex flex-wrap items-center gap-xs pt-xxs">
        <StatusBadge status={project.status} />
        {project.kind ? (
          <span className="rounded-full bg-neutral-8 px-s py-[2px] text-xs text-neutral-60">
            {project.kind}
          </span>
        ) : null}
        <span className="ml-auto text-xs text-neutral-40">{formatRelative(project.updatedAt)}</span>
      </div>

      {project.slug ? (
        <a
          href={`/p/${project.slug}/`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-xxs text-xs text-brand-text hover:underline"
        >
          <Icon name="external" size={12} />/p/{project.slug}
        </a>
      ) : null}

      {confirming ? (
        <div className="absolute inset-0 flex flex-col justify-center gap-s rounded-l bg-base-tertiary p-l backdrop-blur-[2px]">
          <p className="text-base text-neutral-95">删除这个项目？工作区文件也会一起消失。</p>
          {deleteError ? <p className="text-sm text-danger-strong">{deleteError}</p> : null}
          <div className="flex gap-s">
            <Button
              variant="danger"
              size="sm"
              loading={deleting}
              onClick={() => {
                setDeleting(true);
                setDeleteError(null);
                onDelete()
                  .catch((err: unknown) => setDeleteError(errorMessage(err)))
                  .finally(() => setDeleting(false));
              }}
            >
              删除
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
              取消
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
