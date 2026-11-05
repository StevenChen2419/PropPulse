"use client";
import { useEffect, useRef } from "react";

/** Refresh visible pages every minute and on connection/visibility recovery. */
export function useLiveRefresh(refresh: () => unknown | Promise<unknown>, busy = false) {
  const latest = useRef({ refresh, busy });
  latest.current = { refresh, busy };
  useEffect(() => {
    let pending = false;
    let active = true;
    const run = async () => {
      if (!active || document.visibilityState === "hidden" || !navigator.onLine || pending || latest.current.busy) return;
      pending = true;
      try { await latest.current.refresh(); }
      catch { /* Page loaders own their visible error states. */ }
      finally { pending = false; }
    };
    const timer = window.setInterval(run, 60_000);
    document.addEventListener("visibilitychange", run);
    window.addEventListener("online", run);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", run);
      window.removeEventListener("online", run);
    };
  }, []);
}
