import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import AppHeader from "@/components/AppHeader";
import StatusBadge from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { ArrowLeft, Loader2, Copy, ExternalLink, Hourglass } from "lucide-react";

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function Row({ label, children, mono = false, testId }) {
  return (
    <div
      className="flex items-start justify-between gap-6 border-b border-neutral-800/80 py-3 last:border-b-0"
      data-testid={testId}
    >
      <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-neutral-500">
        {label}
      </span>
      <span
        className={`max-w-[70%] text-right text-sm text-neutral-200 ${
          mono ? "break-all font-mono text-xs" : ""
        }`}
      >
        {children}
      </span>
    </div>
  );
}

export default function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const { data } = await api.get(`/jobs/${id}`);
        if (active) setJob(data);
      } catch (e) {
        if (active) setErr(e?.response?.status === 404 ? "Job not found" : "Failed to load job");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [id]);

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(job.url);
      toast.success("URL copied");
    } catch {
      toast.error("Copy failed");
    }
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <AppHeader />

      <main className="mx-auto max-w-4xl px-6 py-10">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("/")}
          className="mb-6 -ml-2 text-neutral-400 hover:bg-neutral-800/60 hover:text-neutral-100"
          data-testid="back-to-dashboard"
        >
          <ArrowLeft className="mr-1.5 h-4 w-4" />
          Back to dashboard
        </Button>

        {loading ? (
          <div className="flex items-center gap-2 text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Loading job…</span>
          </div>
        ) : err ? (
          <div
            className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-6 text-rose-300"
            data-testid="job-error-state"
          >
            {err}
          </div>
        ) : (
          <>
            <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-neutral-500">
                  Job
                </p>
                <h1
                  className="mt-1.5 font-mono text-xl text-neutral-100"
                  data-testid="job-detail-id"
                >
                  {job.id.slice(0, 8)}
                  <span className="text-neutral-600">…</span>
                  {job.id.slice(-4)}
                </h1>
              </div>
              <StatusBadge status={job.status} />
            </div>

            <div
              className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-6"
              data-testid="job-detail-card"
            >
              <Row label="Source URL" testId="job-row-url">
                <div className="flex items-center justify-end gap-2">
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="break-all text-right font-mono text-xs text-emerald-300 hover:text-emerald-200"
                  >
                    {job.url}
                  </a>
                  <button
                    onClick={copyUrl}
                    className="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200"
                    aria-label="Copy URL"
                    data-testid="copy-url-button"
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </button>
                </div>
              </Row>
              <Row label="Status" testId="job-row-status">
                <StatusBadge status={job.status} />
              </Row>
              <Row label="Created" testId="job-row-created">
                {fmtDate(job.created_at)}
              </Row>
              <Row label="Started" testId="job-row-started">
                {fmtDate(job.started_at)}
              </Row>
              <Row label="Finished" testId="job-row-finished">
                {fmtDate(job.finished_at)}
              </Row>
              <Row label="Pages scraped" mono testId="job-row-pages">
                {job.pages_scraped}
              </Row>
              <Row label="Products" mono testId="job-row-products">
                {job.products_count}
              </Row>
              {job.error && (
                <Row label="Error" testId="job-row-error">
                  <span className="text-rose-300">{job.error}</span>
                </Row>
              )}
            </div>

            <div
              className="mt-8 flex items-start gap-3 rounded-xl border border-dashed border-neutral-800 bg-neutral-900/30 p-5"
              data-testid="phase-notice"
            >
              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
                <Hourglass className="h-3.5 w-3.5" />
              </span>
              <div className="text-sm text-neutral-300">
                <p className="font-medium text-neutral-100">
                  Scraper coming in Phase 2
                </p>
                <p className="mt-1 text-xs leading-relaxed text-neutral-400">
                  Live logs, the product table, CSV download and
                  copy-to-clipboard will land once the Playwright worker and SSE
                  stream are wired up.
                </p>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
