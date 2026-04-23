import React from "react";
import { useNavigate, Link } from "react-router-dom";
import { clearToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Terminal, LogOut } from "lucide-react";

export default function AppHeader() {
  const navigate = useNavigate();
  const onLogout = () => {
    clearToken();
    navigate("/login");
  };
  return (
    <header
      className="sticky top-0 z-30 border-b border-neutral-800/80 bg-neutral-950/85 backdrop-blur"
      data-testid="app-header"
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link
          to="/"
          className="group flex items-center gap-3"
          data-testid="header-home-link"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-md border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 transition-colors group-hover:bg-emerald-500/20">
            <Terminal className="h-4 w-4" strokeWidth={2.25} />
          </span>
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-semibold tracking-tight text-neutral-100">
              Ecommerce Data Extractor
            </span>
            <span className="text-[11px] uppercase tracking-[0.18em] text-neutral-500">
              Swagify schema · v0.1
            </span>
          </div>
        </Link>
        <Button
          variant="ghost"
          size="sm"
          onClick={onLogout}
          className="text-neutral-400 hover:bg-neutral-800/60 hover:text-neutral-100"
          data-testid="logout-button"
        >
          <LogOut className="mr-2 h-4 w-4" />
          Logout
        </Button>
      </div>
    </header>
  );
}
