import React, { useEffect, useRef, useState } from "react";
import { api, API, getToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { Download, Copy, Loader2, ChevronDown, ExternalLink } from "lucide-react";

async function fetchBlob(path) {
  const token = getToken();
  const res = await fetch(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res;
}

export async function downloadCsv(jobId) {
  const res = await fetchBlob(`/jobs/${jobId}/export.csv`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `job_${jobId.slice(0, 8)}_swagify.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function ProductTable({ job }) {
  const jobId = job.id;
  const [products, setProducts] = useState([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [exporting, setExporting] = useState(null); // 'csv' | 'txt' | 'copy-csv' | 'copy-tsv' | null
  const seenRef = useRef(new Set());

  const PAGE = 50;

  const addUnique = (items) =>
    items.filter((it) => {
      if (seenRef.current.has(it.id)) return false;
      seenRef.current.add(it.id);
      return true;
    });

  const loadMore = async (reset = false) => {
    if (loading) return;
    setLoading(true);
    try {
      const off = reset ? 0 : offset;
      const { data } = await api.get(
        `/jobs/${jobId}/products?limit=${PAGE}&offset=${off}`
      );
      if (reset) {
        seenRef.current = new Set(data.map((p) => p.id));
        setProducts(data);
      } else {
        setProducts((prev) => [...prev, ...addUnique(data)]);
      }
      setOffset(off + data.length);
      setHasMore(data.length === PAGE);
    } catch {
      toast.error("Failed to load products");
    } finally {
      setLoading(false);
    }
  };

  // initial load
  useEffect(() => {
    loadMore(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  // auto-refresh first page every 4s while running
  useEffect(() => {
    if (job.status !== "running" && job.status !== "queued") return;
    const int = setInterval(async () => {
      try {
        const { data } = await api.get(
          `/jobs/${jobId}/products?limit=${PAGE}&offset=0`
        );
        const fresh = addUnique(data);
        if (fresh.length) {
          setProducts((prev) => [...fresh, ...prev]);
        }
      } catch {
        /* ignore */
      }
    }, 4000);
    return () => clearInterval(int);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, job.status]);

  const disabled = job.products_count === 0;

  const onDownload = async () => {
    setExporting("csv");
    try {
      await downloadCsv(jobId);
      toast.success("CSV downloaded");
    } catch (e) {
      toast.error(`Download failed: ${e.message}`);
    } finally {
      setExporting(null);
    }
  };

  const onCopy = async (kind) => {
    setExporting(kind === "csv" ? "copy-csv" : "copy-tsv");
    try {
      const res = await fetchBlob(
        `/jobs/${jobId}/export.${kind === "csv" ? "csv" : "txt"}`
      );
      const text = await res.text();
      await navigator.clipboard.writeText(text);
      const rows = Math.max(0, text.split("\n").filter(Boolean).length - 1);
      toast.success(`Copied ${rows} rows as ${kind.toUpperCase()}`);
    } catch (e) {
      toast.error(`Copy failed: ${e.message}`);
    } finally {
      setExporting(null);
    }
  };

  return (
    <div data-testid="product-table-section">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-neutral-300">
          Products <span className="ml-2 text-xs text-neutral-500">{products.length} loaded · {job.products_count} total</span>
        </h2>
        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={onDownload}
            disabled={disabled || exporting === "csv"}
            className="bg-emerald-500 font-medium text-neutral-950 hover:bg-emerald-400 disabled:opacity-50"
            data-testid="download-csv-button"
          >
            {exporting === "csv" ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="mr-1.5 h-3.5 w-3.5" />
            )}
            Download CSV
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="sm"
                variant="outline"
                disabled={disabled}
                className="border-neutral-800 bg-neutral-900/60 text-neutral-200 hover:bg-neutral-800"
                data-testid="copy-clipboard-button"
              >
                {exporting?.startsWith("copy-") ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Copy className="mr-1.5 h-3.5 w-3.5" />
                )}
                Copy
                <ChevronDown className="ml-1.5 h-3 w-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="border-neutral-800 bg-neutral-950 text-neutral-100"
            >
              <DropdownMenuItem
                onClick={() => onCopy("csv")}
                className="text-xs focus:bg-neutral-800 focus:text-neutral-100"
                data-testid="copy-as-csv"
              >
                Copy as CSV
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => onCopy("txt")}
                className="text-xs focus:bg-neutral-800 focus:text-neutral-100"
                data-testid="copy-as-tsv"
              >
                Copy as Plain Text (TSV)
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div
        className="overflow-hidden rounded-xl border border-neutral-800 bg-neutral-900/40"
      >
        {products.length === 0 && !loading ? (
          <div
            className="flex h-32 items-center justify-center text-xs text-neutral-500"
            data-testid="products-empty-state"
          >
            {job.status === "running" || job.status === "queued"
              ? "No products yet — they'll appear here as soon as the first page is scraped."
              : "No products found."}
          </div>
        ) : (
          <div className="max-h-[60vh] overflow-auto" data-testid="products-scroll">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-neutral-950/95 backdrop-blur">
                <tr className="border-b border-neutral-800 text-[11px] font-medium uppercase tracking-wider text-neutral-500">
                  <th className="w-14 py-2 pl-4 text-left">Img</th>
                  <th className="py-2 pr-4 text-left">Name</th>
                  <th className="py-2 pr-4 text-right">Price</th>
                  <th className="py-2 pr-4 text-left">Ccy</th>
                  <th className="py-2 pr-4 text-right">Rating</th>
                  <th className="py-2 pr-4 text-right">Reviews</th>
                  <th className="py-2 pr-4 text-left">Brand</th>
                </tr>
              </thead>
              <tbody>
                {products.map((p) => {
                  const d = p.data || {};
                  return (
                    <tr
                      key={p.id}
                      className="border-b border-neutral-900 text-neutral-200 hover:bg-neutral-800/30"
                      data-testid={`product-row-${p.id}`}
                    >
                      <td className="py-2 pl-4">
                        {d.image_url ? (
                          <img
                            src={d.image_url}
                            alt=""
                            loading="lazy"
                            className="h-10 w-10 rounded border border-neutral-800 object-cover"
                          />
                        ) : (
                          <span className="text-neutral-700">—</span>
                        )}
                      </td>
                      <td className="py-2 pr-4">
                        {d.product_url ? (
                          <a
                            href={d.product_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="inline-flex items-center gap-1 text-emerald-300 hover:text-emerald-200"
                          >
                            {d.name || "(no name)"}
                            <ExternalLink className="h-3 w-3 opacity-60" />
                          </a>
                        ) : (
                          <span>{d.name || "(no name)"}</span>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-right font-mono text-xs">
                        {d.price ?? "—"}
                      </td>
                      <td className="py-2 pr-4 text-xs text-neutral-400">
                        {d.currency || "—"}
                      </td>
                      <td className="py-2 pr-4 text-right font-mono text-xs">
                        {d.rating ?? "—"}
                      </td>
                      <td className="py-2 pr-4 text-right font-mono text-xs">
                        {d.review_count ?? "—"}
                      </td>
                      <td className="py-2 pr-4 text-xs text-neutral-400">
                        {d.brand || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {hasMore && products.length > 0 && (
        <div className="mt-3 flex justify-center">
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadMore(false)}
            disabled={loading}
            className="border-neutral-800 bg-neutral-900/60 text-neutral-200 hover:bg-neutral-800"
            data-testid="load-more-products"
          >
            {loading ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Loading…
              </>
            ) : (
              `Load more (${Math.max(0, job.products_count - products.length)} remaining)`
            )}
          </Button>
        </div>
      )}
    </div>
  );
}
