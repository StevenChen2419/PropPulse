"use client";
import { useRef, useState } from "react";
import type { ComparisonOffer, PropSide, SlipSelection } from "@/lib/types";
import { api } from "@/lib/api";
import { useSlip } from "@/store/slip";
import { isActionable, formatOdds } from "@/lib/propSides";
import { SportsbookComparison } from "./SportsbookComparison";

export function SlipSelectionEditor({ item }: { item: SlipSelection }) {
  const [open, setOpen] = useState(false);
  const [side, setSide] = useState(item.side);
  const [subject, setSubject] = useState(item);
  const [choice, setChoice] = useState<ComparisonOffer>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const editButton = useRef<HTMLButtonElement>(null);
  const direction = useRef<HTMLSelectElement>(null);
  const close = () => { setOpen(false); requestAnimationFrame(() => editButton.current?.focus()); };
  const pending = useSlip(s => Boolean(s.pendingIds[item.id]));
  const begin = async () => {
    if (loading || pending) return;
    setOpen(true); setLoading(true); setLoaded(false); setError(null); setChoice(undefined); setSide(item.side);
    requestAnimationFrame(() => direction.current?.focus());
    try {
      const response = await api.getSlip();
      const current = response.slip?.items.find(row => row.prop_id === item.id);
      if (!current?.prop) throw new Error("This selection could not be loaded.");
      setSubject({ ...current.prop, side: current.side, selection: current.selection });
      setLoaded(true);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load alternatives"); }
    finally { setLoading(false); }
  };
  const save = async () => {
    if (!choice || !isActionable(choice, item.game_time) || !useSlip.getState().beginMutation(item.id)) return;
    setError(null);
    try {
      const response = await api.editSlipSelection(item.id, side, { sportsbook: choice.sportsbook, line: choice.line });
      useSlip.getState().addProp(subject, side, response.selection);
      close();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not edit selection. Original kept."); }
    finally { useSlip.getState().endMutation(item.id); }
  };
  if (!open) return <button ref={editButton} type="button" className="my-1 rounded-lg border border-gray-200 px-3 text-xs text-indigo-700" disabled={pending} onClick={begin}>Edit selection</button>;
  return <div aria-label={`Edit ${item.player.name} selection`} aria-busy={loading || pending} className="my-2 rounded-lg border border-gray-200 p-2 text-xs">
    <label>Direction<select ref={direction} aria-label="Edit slip direction" value={side} disabled={pending} onChange={e => { setSide(e.target.value as PropSide); setChoice(undefined); }}
      className="my-2 block w-full rounded border border-gray-200 bg-canvas p-2"><option value="over">Over</option><option value="under">Under</option></select></label>
    {loading ? <p role="status">Loading stored offers…</p> : loaded && <SportsbookComparison comparison={subject.comparison} side={side}
      line={choice?.line ?? item.selection?.line ?? item.line} sportsbook={choice?.sportsbook ?? item.selection?.sportsbook}
      gameTime={item.game_time} busy={pending} onSelect={(offer) => {
        if (!isActionable(offer, item.game_time) || offer.odds == null) { setError("This alternative is unavailable. Original selection kept."); return; }
        setChoice(offer); setError(null);
      }} />}
    {choice && <p className="mb-2 capitalize">New selection: {choice.sportsbook} · {side} {choice.line} · {formatOdds(choice.odds)}</p>}
    <p className="mb-2 text-muted">Choose an available sportsbook, line and direction. Last-known and expired prices cannot replace your selection. Saving a different selection records its original price.</p>
    {error && <p role="alert" className="my-2 text-red-600">{error}</p>}
    {!loaded && !loading && <button type="button" onClick={begin} className="mb-2 underline">Retry loading offers</button>}
    <div className="flex flex-wrap gap-3"><button type="button" disabled={!choice || pending || loading || !isActionable(choice, item.game_time)} onClick={save} className="rounded border border-gray-200 p-2 disabled:opacity-40">Save changes</button>
      <button type="button" disabled={pending || loading} onClick={close}>Cancel</button></div>
  </div>;
}
