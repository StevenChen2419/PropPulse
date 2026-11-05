"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { PropSide, SelectedOffer } from "@/lib/types";
import { requireSession } from "@/store/auth";
import { api } from "@/lib/api";
import { useSavedProps, savedSelectionKey } from "@/store/savedProps";

export function SaveExactSelection({ propId, side, selection, onChange }: {
  propId: string; side: PropSide; selection?: Pick<SelectedOffer, "sportsbook" | "line">;
  onChange?: () => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = selection ? savedSelectionKey(propId, side, selection) : "";
  const savedId = useSavedProps(s => s.exact[key]);
  const toggle = async () => {
    if (!selection || busy) return;
    setBusy(true); setError(null);
    try {
      if (!await requireSession()) { router.push("/login"); return; }
      if (savedId) {
        await api.deleteSavedSelection(savedId);
        useSavedProps.getState().removeExact(key);
      } else {
        const result = await api.saveSelection(propId, side, selection);
        useSavedProps.getState().addExact(key, result.id);
      }
      onChange?.();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not update saved selection"); }
    finally { setBusy(false); }
  };
  return <div className="my-2 text-xs">
    <button type="button" aria-pressed={Boolean(savedId)} disabled={!selection || busy} onClick={toggle}
      className="rounded-lg border border-gray-200 px-3 py-2 text-ink hover:border-indigo-400 disabled:opacity-50">
      {busy ? "Saving…" : savedId ? "Unsave exact selection" : "Save exact selection"}
    </button>
    {error && <p role="alert" className="mt-1 text-red-600">{error}</p>}
  </div>;
}
