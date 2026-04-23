import React, { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, API, getToken } from "@/lib/api";
import AppHeader from "@/components/AppHeader";
import StatusBadge from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  ArrowLeft,
  Loader2,
  Copy,
  Activity,
  Layers,
  Clock,
  Trash2,
  Radio,
} from "lucide-react";

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function elapsed(startIso, endIso) {
  if (!startIso) return "—";
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const s = Math.max(0, Math.floor((end - start) / 1000));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${s}s`;
}

const LEVEL_STYLES = {
  INFO: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  DEBUG: "border-neutral-700 bg-neutral-800/60 text-neutral-400",
  WARN: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  ERROR: "border-rose-500/30 bg-rose-500/10 text-rose-300",
};

function LogLine({ entry }) {
  const cls = LEVEL_STYLES[entry.level] || LEVEL_STYLES.INFO;
  const ts = (() => {
    try {
      return new Date(entry.ts).toLocaleTimeString(undefined, { hour12: false });
    } catch {
      return entry.ts;
    }
  })();
  return (
    <div
      className="group flex items-start gap-3 border-b border-neutral-900 px-4 py-2 font-mono text-xs leading-relaxed hover:bg-neutral-900/50"
      data-testid={`log-entry-${entry.id}`}
    >
      <span className="shrink-0 text-neutral-600">{ts}</span>
      <span
        className={`shrink-0 rounded border px-1.5 py-0 text-[10px] font-semibold uppercase tracking-wider ${cls}`}
      >
        {entry.level}
      </span>
      <span className="min-w-0 flex-1 break-words text-neutral-200">
        {entry.message}
        {entry.meta && Object.keys(entry.meta).length > 0 && (
          <span className="ml-2 text-neutral-600">
            {JSON.stringify(entry.meta)}
          </span>
        )}
      </span>
    </div>
  );
}

export default function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [logs, setLogs] = useState([]);
  const [levelFilter, setLevelFilter] = useState("ALL");
  const [streaming, setStreaming] = useState(false);
  const logsEndRef = useRef(null);
  const logIdsRef = useRef(new Set());
  const esRef = useRef(null);

  // Fetch + poll job metadata
  useEffect(() => {
    let cancelled = false;
    let timer = null;

    const tick = async () => {
      try {
        const { data } = await api.get(`/jobs/${id}`);
        if (cancelled) return;
        setJob(data);
        setErr(null);
        if (data.status === "queued" || data.status === "running") {
          timer = setTimeout(tick, 2000);
        }
      } catch (e) {
        if (!cancelled) {
          setErr(e?.response?.status === 404 ? "Job not found" : "Failed to load job");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  // Open SSE stream
  useEffect(() => {
    const token = getToken();
    if (!token || !id) return;
    const url = `${API}/jobs/${id}/logs/stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    esRef.current = es;
    setStreaming(true);

    es.onmessage = (evt) => {
      try {
        const entry = JSON.parse(evt.data);
        if (logIdsRef.current.has(entry.id)) return;
        logIdsRef.current.add(entry.id);
        setLogs((prev) => [...prev, entry]);
      } catch {
        /* ignore */
      }
    };
    es.addEventListener("end", () => {
      es.close();
      setStreaming(false);
    });
    es.onerror = () => {
      // EventSource auto-reconnects; but if job is terminal we just stop.
      setStreaming(false);
    };
    return () => {
      es.close();
      esRef.current = null;
    };
  }, [id]);

  // Autoscroll
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs.length]);

  const filteredLogs = useMemo(() => {
    if (levelFilter === "ALL") return logs;
    return logs.filter((l) => l.level === levelFilter);
  }, [logs, levelFilter]);

  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(job.url);
      toast.success("URL copied");
    } catch {
      toast.error("Copy failed");
    }
  };

  const onDelete = async () => {
    if (!window.confirm("Delete this job? This also stops the scraper.")) return;
    try {
      await api.delete(`/jobs/${id}`);
      toast.success("Job deleted");
      navigate("/");
    } catch {
      toast.error("Delete failed");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-neutral-950 text-neutral-100">
        <AppHeader />
        <main className="mx-auto max-w-5xl px-6 py-10">
          <div className="flex items-center gap-2 text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Loading job…</span>
          </div>
        </main>
      </div>
    );
  }

  if (err || !job) {
    return (
      <div className="min-h-screen bg-neutral-950 text-neutral-100">
        <AppHeader />
        <main className="mx-auto max-w-5xl px-6 py-10">
          <div
            className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-6 text-rose-300"
            data-testid="job-error-state"
          >
            {err || "Job not found"}
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <AppHeader />

      <main className="mx-auto max-w-5xl px-6 py-10">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("/")}
          className="mb-6 -ml-2 text-neutral-400 hover:bg-neutral-800/60 hover:text-neutral-100"
          data-testid="back-to-dashboard"
        >
          <ArrowLeft className="mr-1.5 h-4 w-4" />
          Back
        </Button>

        <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-neutral-500">
              Job
            </p>
            <div className="mt-1.5 flex items-center gap-3">
              <h1
                className="truncate font-mono text-lg text-neutral-100"
                data-testid="job-detail-id"
              >
                {job.id.slice(0, 8)}
                <span className="text-neutral-600">…</span>
                {job.id.slice(-4)}
              </h1>
              <StatusBadge status={job.status} />
            </div>
            <div className="mt-2 flex items-center gap-2 text-xs text-neutral-500">
              <a
                href={job.url}
                target="_blank"
                rel="noreferrer noopener"
                className="truncate font-mono text-emerald-300 hover:text-emerald-200"
                data-testid="job-detail-url"
              >
                {job.url}
              </a>
              <button
                onClick={copyUrl}
                className="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200"
                data-testid="copy-url-button"
                aria-label="Copy URL"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onDelete}
            className="text-neutral-400 hover:bg-rose-500/10 hover:text-rose-300"
            data-testid="job-delete-button"
          >
            <Trash2 className="mr-1.5 h-4 w-4" />
            Delete
          </Button>
        </div>

        {/* metric cards */}
        <div
          className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4"
          data-testid="job-metrics"
        >
          <Metric
            icon={<Layers className="h-3.5 w-3.5" />}
            label="Pages scraped"
            value={job.pages_scraped}
            mono
            testId="metric-pages"
          />
          <Metric
            icon={<Activity className="h-3.5 w-3.5" />}
            label="Products"
            value={job.products_count}
            mono
            testId="metric-products"
          />
          <Metric
            icon={<Clock className="h-3.5 w-3.5" />}
            label="Elapsed"
            value={elapsed(job.started_at, job.finished_at)}
            testId="metric-elapsed"
          />
          <Metric
            icon={<Radio className="h-3.5 w-3.5" />}
            label="Started"
            value={job.started_at ? fmtDate(job.started_at) : "—"}
            testId="metric-started"
            small
          />
        </div>

        {job.error && (
          <div
            className="mb-6 rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300"
            data-testid="job-error-banner"
          >
            <span className="font-semibold">Error: </span>
            <span className="font-mono text-xs">{job.error}</span>
          </div>
        )}

        <p
          className="mb-6 text-xs text-neutral-500"
          data-testid="phase3-note"
        >
          {job.products_count} products captured so far — full product table
          coming in Phase 3.
        </p>

        {/* Logs panel */}
        <div
          className="overflow-hidden rounded-xl border border-neutral-800 bg-neutral-900/40"
          data-testid="logs-panel"
        >
          <div className="flex items-center justify-between border-b border-neutral-800 bg-neutral-900/60 px-4 py-3">
            <div className="flex items-center gap-2.5">
              <span
                className={`inline-flex h-2 w-2 rounded-full ${
                  streaming ? "bg-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.7)]" : "bg-neutral-600"
                }`}
              />
              <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-neutral-300">
                Live logs
              </h2>
              <span className="text-xs text-neutral-500">
                {streaming ? "streaming" : "idle"} · {filteredLogs.length} shown
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Select value={levelFilter} onValueChange={setLevelFilter}>
                <SelectTrigger
                  className="h-8 w-[120px] border-neutral-800 bg-neutral-950/60 text-xs text-neutral-300"
                  data-testid="log-level-filter"
                >
                  <SelectValue placeholder="Level" />
                </SelectTrigger>
                <SelectContent className="border-neutral-800 bg-neutral-950 text-neutral-100">
                  <SelectItem value="ALL">All levels</SelectItem>
                  <SelectItem value="INFO">INFO</SelectItem>
                  <SelectItem value="DEBUG">DEBUG</SelectItem>
                  <SelectItem value="WARN">WARN</SelectItem>
                  <SelectItem value="ERROR">ERROR</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div
            className="h-[440px] overflow-y-auto bg-neutral-950"
            data-testid="logs-scroll"
          >
            {filteredLogs.length === 0 ? (
              <div className="flex h-full items-center justify-center text-xs text-neutral-600">
                Waiting for logs…
              </div>
            ) : (
              filteredLogs.map((l) => <LogLine key={l.id} entry={l} />)
            )}
            <div ref={logsEndRef} />
          </div>
        </div>
      </main>
    </div>
  );
}

function Metric({ icon, label, value, mono = false, small = false, testId }) {
  return (
    <div
      className="rounded-xl border border-neutral-800 bg-neutral-900/40 p-4"
      data-testid={testId}
    >
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-neutral-500">
        <span className="text-emerald-400">{icon}</span>
        {label}
      </div>
      <div
        className={`mt-1.5 text-neutral-100 ${
          small ? "text-xs" : mono ? "font-mono text-2xl" : "text-lg"
        }`}
      >
        {value}
      </div>
    </div>
  );
}
