"use client";
import Link from "next/link";
import { useLiveRefresh } from "@/lib/useLiveRefresh";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bookmark, AlertCircle, RefreshCw } from "lucide-react";
import { useAuth, restoreSession } from "@/store/auth";
import { api }       from "@/lib/api";
import type { Prop, SavedSelection } from "@/lib/types";
import { useSavedProps, savedSelectionKey } from "@/store/savedProps";
import { useSlip } from "@/store/slip";
import { propResearchHref } from "@/lib/gameNavigation";
import { SelectionPrice } from "@/components/SelectionPrice";
import { useOfferClock } from "@/lib/useOfferClock";
import { PropCard }  from "@/components/PropCard";

export default function SavedPage() {
  const router = useRouter();
  useOfferClock();
  const [selections, setSelections] = useState<SavedSelection[]>([]);
  const [search, setSearch] = useState("");
  const [sport, setSport] = useState("");
  const [kind, setKind] = useState("all");
  const [busy, setBusy] = useState<string | null>(null);
  const actionPending = useRef(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [saved,   setSaved]   = useState<Prop[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);
  const authStatus = useAuth(s => s.status);
  const authed = authStatus === "authenticated";

  const load = () => {
    setLoading(true);
    setError(null);
    return api
      .getSaved()
      .then((r) => {
        setSaved(r.saved ?? []); setSelections(r.selections ?? []);
        useSavedProps.getState().setIds((r.saved ?? []).map(p => p.id));
        useSavedProps.getState().setExact(r.selections ?? []);
      })
      .catch((e: any) => setError(e.message || "Failed to load saved props."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (authStatus === "anonymous") { router.push("/login"); return; }
    if (authStatus === "authenticated") { void load(); return; }
    if (authStatus === "error") { setError("Account temporarily unavailable. Please retry."); setLoading(false); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authStatus]);

  useLiveRefresh(load, loading || !authed || busy != null);
  const matches = (p: Prop) => (!sport || p.player.sport === sport) &&
    `${p.player.name} ${p.prop_type.replace(/_/g, " ")}`.toLowerCase().includes(search.trim().toLowerCase());
  const bookmarks = kind === "exact" ? [] : saved.filter(matches);
  const exact = kind === "bookmarks" ? [] : selections.filter(row => matches(row.prop));
  const act = async (row: SavedSelection, remove: boolean) => {
    if (actionPending.current) return;
    if (!remove && !useSlip.getState().beginMutation(row.prop_id)) {
      setActionError("Your research slip is loading or unavailable. Retry loading it before adding a selection.");
      return;
    }
    actionPending.current = true;
    setBusy(row.id); setActionError(null);
    try {
      if (remove) {
        await api.deleteSavedSelection(row.id);
        setSelections(rows => rows.filter(s => s.id !== row.id));
        useSavedProps.getState().removeExact(savedSelectionKey(row.prop_id, row.side, row.selection));
      } else {
        const result = await api.addSavedSelectionToSlip(row.id);
        useSlip.getState().addProp(row.prop, row.side, result.selection);
        window.dispatchEvent(new Event("proppulse:open-slip"));
      }
    } catch (e) { setActionError(e instanceof Error ? e.message : "Could not update selection"); }
    finally { if (!remove) useSlip.getState().endMutation(row.prop_id); actionPending.current = false; setBusy(null); }
  };

  if (authStatus === "error") return <main className="workspace"><p role="alert">{error}</p><button className="button" onClick={() => { void restoreSession().catch(() => {}); }}>Retry account</button></main>;

  if (!authed || (loading && !saved.length && !selections.length)) {
    return (
      <main className="min-h-screen bg-gray-50">
        <div className="workspace space-y-3">
          <p role="status" className="text-sm text-muted">Loading saved bookmarks and exact selections…</p>
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="bg-white rounded-2xl border border-gray-100 h-40 animate-pulse"
            />
          ))}
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="workspace">

        <div className="page-heading">
          <div>
            <p className="eyebrow">Your research library</p><h1 className="page-title">Saved Props</h1><p className="page-description mb-3">Keep props to revisit with current availability. Bookmarks save the prop. Exact selections preserve a sportsbook, line, side and original observed price.</p>
            <p className="text-sm text-gray-400 mt-1">
              {saved.length} bookmarks · {selections.length} exact selections
            </p>
          </div>
          <button
            onClick={load}
            disabled={loading || busy != null}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 border border-gray-200 px-3 py-1.5 rounded-lg transition-colors"
          >
            <RefreshCw size={12} />
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="text-xs text-muted">Search player or market<input aria-label="Search saved props" value={search} onChange={e => setSearch(e.target.value)} className="mt-1 w-full rounded-lg border border-gray-200 bg-canvas p-2 text-sm" /></label>
          <label className="text-xs text-muted">Sport<select aria-label="Saved sport" value={sport} onChange={e => setSport(e.target.value)} className="mt-1 w-full rounded-lg border border-gray-200 bg-canvas p-2 text-sm"><option value="">All sports</option>{[...new Set([...saved, ...selections.map(s => s.prop)].map(p => p.player.sport))].sort().map(s => <option key={s}>{s}</option>)}</select></label>
          <label className="text-xs text-muted">Saved type<select aria-label="Saved type" value={kind} onChange={e => setKind(e.target.value)} className="mt-1 w-full rounded-lg border border-gray-200 bg-canvas p-2 text-sm"><option value="all">All saved items</option><option value="bookmarks">Generic bookmarks</option><option value="exact">Exact selections</option></select></label>
        </div>
        {actionError && <p role="alert" className="mb-4 text-sm text-red-600">{actionError}</p>}
        {!error && !bookmarks.length && !exact.length && (saved.length + selections.length > 0) && <p className="my-4 text-muted">No saved items match these filters.</p>}
        {!error && exact.length > 0 && <section aria-label="Exact saved selections" className="mb-6">
          <h2 className="mb-3 font-semibold text-ink">Exact saved selections</h2>
          <div className="prop-grid">{exact.map(row => <article key={row.id} className="min-w-0 rounded-xl border border-gray-200 bg-white p-4">
            <p className="text-xs text-muted">Exact selection · {row.prop.player.sport}</p>
            <Link className="mt-1 block font-semibold text-ink" href={propResearchHref(row.prop.player.id, row.prop_id, { ...row.selection, side: row.side })}>{row.prop.player.name}</Link>
            <p className="mt-2 break-words text-sm capitalize">{row.prop.prop_type.replace(/_/g, " ")} · {row.side} {row.selection.line} · {row.selection.sportsbook}</p>
            <SelectionPrice selection={row.selection} gameTime={row.prop.game_time} />
            <div className="flex flex-wrap gap-3 text-xs"><Link className="py-2 text-indigo-600" href={propResearchHref(row.prop.player.id, row.prop_id, { ...row.selection, side: row.side })}>Research exact line</Link>
              <button disabled={busy != null} aria-busy={busy === row.id} className="py-2 text-indigo-600 disabled:opacity-40" onClick={() => act(row, false)}>Add to research slip</button>
              <button disabled={busy != null} className="py-2 text-red-600 disabled:opacity-40" onClick={() => act(row, true)}>Unsave selection</button></div>
          </article>)}</div>
          <p className="mt-3 text-xs text-muted">Unavailable selections stay saved. Only live prices enter slip estimates.</p>
        </section>}
        {/* Error */}
        {error && (
          <div role="alert" className="bg-red-50 border border-red-100 rounded-xl p-5 mb-5 flex flex-col items-center text-center">
            <AlertCircle size={20} className="text-red-400 mb-2" />
            <p className="text-sm font-medium text-red-700">
              Could not load saved props
            </p>
            <p className="text-xs text-red-400 mt-1 mb-3">{error}</p>
            <button
              onClick={load}
              className="flex items-center gap-1.5 text-xs text-red-600 border border-red-200 px-3 py-1.5 rounded-lg hover:text-red-800 transition-colors"
            >
              <RefreshCw size={12} />
              Try again
            </button>
          </div>
        )}

        {/* Empty */}
        {!error && saved.length === 0 && selections.length === 0 && (
          <div className="empty-state">
            <div className="flex justify-center mb-4">
              <Bookmark size={40} className="text-gray-200" />
            </div>
            <p className="font-medium text-gray-700">No saved props yet</p>
            <p className="text-sm text-gray-400 mt-1">
              Tap the bookmark icon on any prop card to save it here
            </p><Link href="/discover" className="button mt-5">Explore Discover</Link>
          </div>
        )}

        {/* List */}
        {!error && bookmarks.length > 0 && (
          <section aria-label="Generic bookmarks"><h2 className="mb-3 font-semibold text-ink">Generic bookmarks</h2><div className="prop-grid">
            {bookmarks.map((p) => (
              // onUnsave reloads this page's list so the card disappears.
              // PropCard only calls onUnsave after a successful unsave,
              // not after like, dislike, or slip operations.
              <PropCard key={p.id} prop={p} onUnsave={load} onExactChange={load} />
            ))}
          </div></section>
        )}

      </div>
    </main>
  );
}
