"use client";
import { useOfferClock } from "@/lib/useOfferClock";
import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { propResearchHref } from "@/lib/gameNavigation";
import { ChevronUp, ChevronDown, X } from "lucide-react";
import { useSlip } from "@/store/slip";
import { useAuth, requireSession } from "@/store/auth";
import { api }     from "@/lib/api";
import { useLiveRefresh } from "@/lib/useLiveRefresh";
import type { SlipSelection } from "@/lib/types";
import { ParlayCalculator } from "./ParlayCalculator";
import { SlipSelectionEditor } from "./SlipSelectionEditor";
import { SelectionPrice } from "./SelectionPrice";
import { StatisticsStatus } from '@/components/DataStatus';

export function SlipDrawer() {
  const { items, removeProp, pendingIds, beginMutation, endMutation, loadError, loading } = useSlip();
  const [retrying, setRetrying] = useState(false);
  const retry = async () => {
    if (retrying) return;
    setRequested(true);
    setRetrying(true);
    try {
      if (!await requireSession()) return;
      const response = await api.getSlip();
      useSlip.getState().initialize((response.slip?.items ?? []).filter(row => row.prop != null)
        .map(row => ({ ...row.prop!, side: row.side, selection: row.selection })), true);
      useSlip.getState().setLoadError(null);
    } catch { useSlip.getState().setLoadError("Could not load your saved research slip. Retry to recover your selections."); }
    finally { setRetrying(false); }
  };
  useOfferClock();
  const anyPending = Object.keys(pendingIds).length > 0;
  const [requested, setRequested] = useState(false);
  const tabRef = useRef<HTMLButtonElement>(null);
  const [open,     setOpen]     = useState(true);
  const [clearing, setClearing] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Keep the initial mobile workspace clear; the persistent tab opens the slip.
  useEffect(() => {
    if (window.matchMedia("(max-width: 767px)").matches) setOpen(false);
  }, []);

  useLiveRefresh(async () => {
    if (!items.length || useAuth.getState().status !== "authenticated") return;
    const response = await api.getSlip();
    const current = (response.slip?.items ?? []).filter((item) => item.prop != null)
      .map((item): SlipSelection => ({ ...item.prop!, side: item.side, selection: item.selection }));
    useSlip.getState().refreshAvailability(current);
  }, anyPending || clearing);

  useEffect(() => {
    const show = () => { setRequested(true); setOpen(true); requestAnimationFrame(() => tabRef.current?.focus()); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape" && open && tabRef.current?.closest("[role=region]")?.contains(document.activeElement)) { setOpen(false); tabRef.current?.focus(); } };
    const collapse = () => setOpen(false);
    window.addEventListener("proppulse:collapse-slip", collapse);
    window.addEventListener("proppulse:open-slip", show);
    window.addEventListener("keydown", escape);
    return () => { window.removeEventListener("proppulse:collapse-slip", collapse); window.removeEventListener("proppulse:open-slip", show); window.removeEventListener("keydown", escape); };
  }, [open]);
  if (items.length === 0 && !requested && !loadError) return null;

  const handleRemove = async (propId: string) => {
    if (!beginMutation(propId)) return;
    setRemoving(propId);
    setError(null);
    try {
      await api.removeFromSlip(propId);
      removeProp(propId);
    } catch {
      setError("Could not remove this pick. Please try again.");
    } finally {
      endMutation(propId);
      setRemoving(null);
    }
  };

  // Keep any failed removals visible so the displayed selections match storage.
  const handleClearAll = async () => {
    if (Object.keys(useSlip.getState().pendingIds).length > 0) return;
    const ids = items.map((p) => p.id);
    ids.forEach((id) => beginMutation(id));
    setClearing(true);
    setError(null);
    for (const id of ids) {
      try {
        await api.removeFromSlip(id);
        removeProp(id);
      } catch {
        setError("Some picks could not be removed. Please try again.");
      } finally {
        endMutation(id);
      }
    }
    setClearing(false);
  };

  return (
    <div role="region" aria-label="Research slip" className="fixed bottom-3 right-3 z-50 w-[calc(100%-1.5rem)] max-w-sm rounded-2xl border border-gray-200 shadow-float sm:right-6 sm:w-96">

      {/* Tab */}
      <button
        ref={tabRef}
        aria-controls="research-slip-body"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-full flex items-center justify-between bg-slate-900 text-ink px-4 py-3 rounded-t-2xl text-sm font-medium hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
      >
        <div className="flex items-center gap-2.5">
          <span className="bg-blue-600 text-[#ffffff] text-xs w-5 h-5 rounded-full flex items-center justify-center font-bold leading-none">
            {items.length}
          </span>
          <span>My Slip</span>
        </div>
        {open
          ? <ChevronDown size={15} className="text-gray-400" />
          : <ChevronUp   size={15} className="text-gray-400" />
        }
      </button>

      {/* Body */}
      {open && (
        <div id="research-slip-body" className="max-h-[65dvh] overflow-y-auto bg-white border border-gray-200 border-t-0 rounded-b-xl shadow-xl">

          {loading && <p role="status" className="p-4 text-sm text-muted">Loading research slip…</p>}
          {loadError && <div className="p-4"><p role="alert" className="text-sm text-red-600">{loadError}</p><button type="button" onClick={retry} disabled={retrying} className="button mt-3">{retrying ? 'Retrying…' : 'Retry slip'}</button></div>}
          {!loading && !loadError && items.length === 0 && <div className="px-5 py-8 text-center"><p className="font-semibold text-ink">Your research slip is empty</p><p className="mt-2 text-sm text-muted">Choose a side and sportsbook on a prop to start comparing picks.</p><Link href="/discover" className="button mt-4" onClick={() => setOpen(false)}>Explore Discover</Link></div>}
          {/* Items */}
          <div className="divide-y divide-gray-100">
            {items.map((prop) => (
              <div
                key={prop.id}
                className="relative px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                <div className="min-w-0">
                  <Link href={propResearchHref(prop.player.id, prop.id, prop.selection ? { ...prop.selection, side: prop.side } : undefined)} className="mr-10 block text-sm font-semibold text-ink hover:text-blue-500" onClick={() => setOpen(false)}>{prop.player.name}</Link>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
                    <span className={`rounded-md px-1.5 py-0.5 font-semibold ${prop.side === "under" ? "bg-indigo-50 text-indigo-700" : "bg-emerald-50 text-emerald-700"}`}>
                      {prop.side === "under" ? "Under" : "Over"} {prop.selection?.line ?? prop.line}
                    </span>
                    <span className="capitalize text-gray-500">{prop.prop_type.replace(/_/g, " ")}</span>
                  </div>
                  <p className="mt-1 text-[10px] text-gray-400">{prop.selection?.sportsbook ?? prop.sportsbook}</p>
                  <StatisticsStatus coverage={prop.statistics_coverage} />
                  <SelectionPrice selection={prop.selection} gameTime={prop.game_time} />
                  <SlipSelectionEditor item={prop} />
                </div>

                <div className="absolute right-2 top-2">
                  <button
                    onClick={() => handleRemove(prop.id)}
                    disabled={clearing || removing != null || Boolean(pendingIds[prop.id])}
                    aria-label={`Remove ${prop.player.name} ${prop.side} ${prop.selection?.line ?? prop.line} from slip`}
                    title="Remove"
                    className="text-gray-400 hover:text-red-500 transition-colors w-8 h-8 flex items-center justify-center rounded-lg hover:bg-red-50 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                  >
                    <X size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {items.length > 0 && <ParlayCalculator items={items} busy={anyPending || clearing} />}
          {/* Footer actions */}
          {error && <p role="alert" className="px-3 py-2 text-xs text-red-700 bg-red-50">{error}</p>}
          <div className="p-3 flex gap-2 border-t border-gray-100">
            <p className="flex-1 text-xs leading-relaxed text-muted">Research only. Confirm final prices and place bets with your sportsbook.</p>
            <button
              onClick={handleClearAll}
              disabled={!items.length || clearing || removing != null || anyPending}
              title="Remove all from slip"
              className="px-3 py-2.5 text-xs text-gray-400 hover:text-gray-700 border border-gray-200 hover:border-gray-300 rounded-lg transition-colors disabled:opacity-50"
            >
              {clearing ? "..." : "Clear"}
            </button>
          </div>

        </div>
      )}
    </div>
  );
}
