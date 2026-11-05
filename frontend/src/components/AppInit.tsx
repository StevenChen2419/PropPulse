"use client";
import { useEffect } from "react";
import { useAuth, restoreSession, clearSession } from "@/store/auth";
import { api }           from "@/lib/api";
import { useSavedProps } from "@/store/savedProps";
import { useSlip }       from "@/store/slip";
import type { Prop, SlipSelection } from "@/lib/types";

export function AppInit() {
  const status = useAuth(s => s.status);
  const userId = useAuth(s => s.user?.id);
  useEffect(() => {
    // Remove the legacy bearer credential without reading it.
    try { localStorage.removeItem("token"); } catch { /* Storage can be disabled. */ }
    const expired = () => clearSession();
    window.addEventListener("proppulse:unauthorized", expired);
    void restoreSession().catch(() => {});
    return () => window.removeEventListener("proppulse:unauthorized", expired);
  }, []);
  const { setIds }               = useSavedProps();
  const { initialize: initSlip } = useSlip();

  useEffect(() => {
    if (status !== "authenticated") {
      if (status === "error") {
        useSlip.getState().setLoadError("Could not restore your session. Retry to recover your selections.");
        useSlip.getState().finishLoading();
      }
      return;
    }
    useSlip.setState({ loading: true, loadError: null });
    let cancelled = false;
    const current = () => !cancelled && useAuth.getState().status === "authenticated" && useAuth.getState().user?.id === userId;

    // Load saved prop IDs so PropCard bookmark icons reflect server state.
    api
      .getSaved()
      .then((r) => {
        const ids = (r.saved ?? []).map((p: Prop) => p.id);
        if (current()) setIds(ids);
        if (current()) useSavedProps.getState().setExact(r.selections ?? [], true);
      })
      .catch(() => {
        // Non-critical. Bookmark icons default to unsaved state.
      });

    // Load slip items so SlipDrawer reflects server state.
    api
      .getSlip()
      .then((r) => {
        if (!current()) return;
        const props = (r.slip?.items ?? [])
          .filter((item) => item.prop != null)
          .map((item): SlipSelection => ({
            ...item.prop!,
            side: item.side === "under" ? "under" : "over",
            selection: item.selection,
          }));
        initSlip(props, true);
      })
      .catch(() => {
        if (current()) useSlip.getState().setLoadError("Could not load your saved research slip. Retry to recover your selections.");
      })
      .finally(() => {
        if (current()) useSlip.getState().finishLoading();
      });

    return () => { cancelled = true; };

  }, [status, userId, setIds, initSlip]);

  return null;
}
