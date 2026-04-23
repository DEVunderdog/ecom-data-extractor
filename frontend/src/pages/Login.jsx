import React, { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { api, saveToken, isAuthed } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Loader2, Terminal, ShieldCheck } from "lucide-react";

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  if (isAuthed()) {
    return null;
  }

  const onSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      saveToken(data.access_token);
      toast.success("Signed in");
      const dest = location.state?.from?.pathname || "/";
      navigate(dest, { replace: true });
    } catch (err) {
      const msg =
        err?.response?.data?.detail === "Invalid email or password"
          ? "Invalid email or password"
          : err?.response?.status === 422
            ? "Please enter a valid email"
            : "Sign in failed";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-neutral-950 text-neutral-100">
      {/* subtle grid bg */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 18% 12%, rgba(16,185,129,0.10), transparent 45%), radial-gradient(circle at 88% 90%, rgba(16,185,129,0.06), transparent 50%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
          backgroundSize: "48px 48px",
        }}
      />

      <div className="relative mx-auto flex min-h-screen max-w-6xl items-center justify-center px-6 py-12">
        <div className="grid w-full grid-cols-1 gap-12 lg:grid-cols-2">
          {/* Left: brand story */}
          <div className="hidden flex-col justify-between lg:flex">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-md border border-emerald-500/30 bg-emerald-500/10 text-emerald-400">
                <Terminal className="h-4 w-4" strokeWidth={2.25} />
              </span>
              <span className="text-sm font-medium tracking-tight text-neutral-200">
                Ecommerce Data Extractor
              </span>
            </div>

            <div className="space-y-5">
              <h1
                className="text-4xl font-semibold leading-[1.05] tracking-tight text-neutral-50 sm:text-5xl"
                data-testid="login-hero-title"
              >
                Paste a URL.
                <br />
                <span className="text-emerald-400">Get the catalog.</span>
              </h1>
              <p className="max-w-md text-sm leading-relaxed text-neutral-400">
                Autonomous Playwright workers walk every paginated page of an
                e-commerce listing and stream it into a fixed 200-column Swagify
                CSV — live logs included.
              </p>
              <ul className="space-y-2.5 text-sm text-neutral-400">
                <li className="flex items-center gap-2.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  JSON-LD · microdata · heuristic DOM fallback
                </li>
                <li className="flex items-center gap-2.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  rel=next · load-more · infinite scroll detection
                </li>
                <li className="flex items-center gap-2.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  UA rotation · exp. backoff · 3-retry cap
                </li>
              </ul>
            </div>

            <p className="text-[11px] uppercase tracking-[0.22em] text-neutral-600">
              Phase 1 · Skeleton build
            </p>
          </div>

          {/* Right: form card */}
          <div className="flex items-center">
            <div
              className="w-full rounded-xl border border-neutral-800 bg-neutral-900/60 p-8 shadow-[0_1px_0_rgba(255,255,255,0.04)_inset,0_20px_60px_-20px_rgba(0,0,0,0.8)] backdrop-blur"
              data-testid="login-card"
            >
              <div className="mb-7 space-y-1.5">
                <h2 className="text-2xl font-semibold tracking-tight text-neutral-50">
                  Sign in
                </h2>
                <p className="text-sm text-neutral-400">
                  Use the seeded admin account to continue.
                </p>
              </div>

              <form onSubmit={onSubmit} className="space-y-5" data-testid="login-form">
                <div className="space-y-2">
                  <Label
                    htmlFor="email"
                    className="text-xs font-medium uppercase tracking-wider text-neutral-400"
                  >
                    Email
                  </Label>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="admin@extractor.app"
                    className="h-11 border-neutral-800 bg-neutral-950/60 text-neutral-100 placeholder:text-neutral-600 focus-visible:ring-emerald-500/40"
                    data-testid="login-email-input"
                  />
                </div>

                <div className="space-y-2">
                  <Label
                    htmlFor="password"
                    className="text-xs font-medium uppercase tracking-wider text-neutral-400"
                  >
                    Password
                  </Label>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="h-11 border-neutral-800 bg-neutral-950/60 text-neutral-100 placeholder:text-neutral-600 focus-visible:ring-emerald-500/40"
                    data-testid="login-password-input"
                  />
                </div>

                <Button
                  type="submit"
                  disabled={loading}
                  className="h-11 w-full bg-emerald-500 font-medium text-neutral-950 transition-colors hover:bg-emerald-400 disabled:opacity-70"
                  data-testid="login-submit-button"
                >
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Signing in…
                    </>
                  ) : (
                    "Sign in"
                  )}
                </Button>

                <div
                  className="flex items-start gap-2.5 rounded-md border border-neutral-800 bg-neutral-950/60 p-3"
                  data-testid="login-seed-hint"
                >
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                  <div className="text-xs text-neutral-400">
                    Default admin: <span className="text-neutral-200">admin@extractor.app</span>
                    {" / "}
                    <span className="text-neutral-200">admin123</span>
                  </div>
                </div>
              </form>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
