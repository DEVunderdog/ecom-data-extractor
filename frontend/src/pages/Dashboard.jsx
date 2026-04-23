import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import AppHeader from "@/components/AppHeader";
import StatusBadge from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import {
  ArrowRight,
  Link2,
  Loader2,
  Play,
  Plus,
  Trash2,
  Eye,
  Inbox,
} from "lucide-react";

function truncate(s, n = 64) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [confirmId, setConfirmId] = useState(null);

  const fetchJobs = async () => {
    try {
      const { data } = await api.get("/jobs");
      setJobs(data);
    } catch {
      toast.error("Failed to load jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
  }, []);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!url.trim()) return;
    setSubmitting(true);
    try {
      const { data } = await api.post("/jobs", { url: url.trim() });
      setJobs((prev) => [data, ...prev]);
      setUrl("");
      toast.success("Job queued", {
        description: truncate(data.url, 80),
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail[0]?.msg || "Invalid URL"
        : typeof detail === "string"
          ? detail
          : "Could not create job";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const doDelete = async () => {
    if (!confirmId) return;
    const id = confirmId;
    setConfirmId(null);
    try {
      await api.delete(`/jobs/${id}`);
      setJobs((prev) => prev.filter((j) => j.id !== id));
      toast.success("Job deleted");
    } catch {
      toast.error("Delete failed");
    }
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <AppHeader />

      <main className="mx-auto max-w-6xl px-6 py-10">
        {/* Hero / input */}
        <section className="mb-10" data-testid="extract-section">
          <div className="mb-6 flex items-baseline justify-between">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-neutral-500">
                Extractor
              </p>
              <h1 className="mt-1.5 text-3xl font-semibold tracking-tight text-neutral-50 sm:text-4xl">
                Paste a product URL
              </h1>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-neutral-400">
                We&apos;ll queue an autonomous scraper that walks every page
                and writes a 200-column Swagify CSV.
              </p>
            </div>
          </div>

          <form
            onSubmit={onSubmit}
            className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-2.5 shadow-[0_1px_0_rgba(255,255,255,0.04)_inset]"
            data-testid="new-job-form"
          >
            <div className="flex flex-col gap-2.5 sm:flex-row">
              <div className="relative flex-1">
                <Link2 className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-500" />
                <Input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://store.example.com/collections/shoes"
                  className="h-12 border-neutral-800 bg-neutral-950/60 pl-10 pr-3 text-neutral-100 placeholder:text-neutral-600 focus-visible:ring-emerald-500/40"
                  data-testid="new-job-url-input"
                />
              </div>
              <Button
                type="submit"
                disabled={submitting || !url.trim()}
                className="h-12 gap-2 bg-emerald-500 px-6 font-medium text-neutral-950 hover:bg-emerald-400 disabled:opacity-60 sm:min-w-[170px]"
                data-testid="extract-data-button"
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" strokeWidth={2.5} />
                )}
                {submitting ? "Queueing…" : "Extract Data"}
              </Button>
            </div>
          </form>
        </section>

        {/* Jobs table */}
        <section data-testid="jobs-section">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-baseline gap-3">
              <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-neutral-300">
                Jobs
              </h2>
              <span
                className="text-xs text-neutral-500"
                data-testid="jobs-count"
              >
                {loading ? "loading…" : `${jobs.length} total`}
              </span>
            </div>
          </div>

          <div
            className="overflow-hidden rounded-xl border border-neutral-800 bg-neutral-900/40"
            data-testid="jobs-table-wrapper"
          >
            {loading ? (
              <div className="flex items-center justify-center py-16 text-neutral-500">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                <span className="text-sm">Loading jobs…</span>
              </div>
            ) : jobs.length === 0 ? (
              <div
                className="flex flex-col items-center justify-center gap-3 py-20 text-center"
                data-testid="jobs-empty-state"
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-full border border-neutral-800 bg-neutral-950 text-neutral-500">
                  <Inbox className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm font-medium text-neutral-200">
                    No jobs yet
                  </p>
                  <p className="mt-1 text-xs text-neutral-500">
                    Paste a product URL above to queue your first extraction.
                  </p>
                </div>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="border-neutral-800 hover:bg-transparent">
                    <TableHead className="h-11 text-[11px] font-medium uppercase tracking-wider text-neutral-500">
                      URL
                    </TableHead>
                    <TableHead className="h-11 w-[130px] text-[11px] font-medium uppercase tracking-wider text-neutral-500">
                      Status
                    </TableHead>
                    <TableHead className="h-11 w-[140px] text-[11px] font-medium uppercase tracking-wider text-neutral-500">
                      Created
                    </TableHead>
                    <TableHead className="h-11 w-[90px] text-right text-[11px] font-medium uppercase tracking-wider text-neutral-500">
                      Products
                    </TableHead>
                    <TableHead className="h-11 w-[120px] text-right text-[11px] font-medium uppercase tracking-wider text-neutral-500">
                      Actions
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map((j) => (
                    <TableRow
                      key={j.id}
                      onClick={() => navigate(`/jobs/${j.id}`)}
                      className="cursor-pointer border-neutral-800 transition-colors hover:bg-neutral-800/30"
                      data-testid={`job-row-${j.id}`}
                    >
                      <TableCell className="py-3 font-mono text-xs text-neutral-200">
                        {truncate(j.url, 72)}
                      </TableCell>
                      <TableCell className="py-3">
                        <StatusBadge status={j.status} />
                      </TableCell>
                      <TableCell className="py-3 text-xs text-neutral-400">
                        {fmtDate(j.created_at)}
                      </TableCell>
                      <TableCell className="py-3 text-right font-mono text-xs text-neutral-300">
                        {j.products_count ?? 0}
                      </TableCell>
                      <TableCell
                        className="py-3 text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => navigate(`/jobs/${j.id}`)}
                            className="h-8 px-2 text-neutral-400 hover:bg-neutral-800/60 hover:text-emerald-300"
                            data-testid={`view-job-${j.id}`}
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setConfirmId(j.id)}
                            className="h-8 px-2 text-neutral-400 hover:bg-rose-500/10 hover:text-rose-300"
                            data-testid={`delete-job-${j.id}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </section>
      </main>

      <AlertDialog
        open={Boolean(confirmId)}
        onOpenChange={(o) => !o && setConfirmId(null)}
      >
        <AlertDialogContent
          className="border-neutral-800 bg-neutral-950 text-neutral-100"
          data-testid="delete-confirm-dialog"
        >
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this job?</AlertDialogTitle>
            <AlertDialogDescription className="text-neutral-400">
              This removes the job and all associated products and logs.
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              className="border-neutral-800 bg-transparent text-neutral-200 hover:bg-neutral-800"
              data-testid="delete-cancel-button"
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={doDelete}
              className="bg-rose-500 text-neutral-950 hover:bg-rose-400"
              data-testid="delete-confirm-button"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
