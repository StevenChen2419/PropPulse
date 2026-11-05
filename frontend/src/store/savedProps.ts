import { create } from "zustand";
import type { SavedSelection } from "@/lib/types";

export const savedSelectionKey = (propId: string, side: string, selection: { sportsbook: string; line: number }) =>
  JSON.stringify([propId, selection.sportsbook, selection.line, side]);

// Stores only saved prop IDs (not full prop objects).
// Keyed as a plain object so Zustand shallow equality works correctly.
// PropCard reads from this store to decide whether to show a filled bookmark.

interface SavedPropsStore {
  exact: Record<string, string>;
  changedExact: Record<string, true>;
  setExact: (rows: SavedSelection[], preserveChanges?: boolean) => void;
  addExact: (key: string, id: string) => void;
  removeExact: (key: string) => void;
  ids:    Record<string, true>;
  setIds: (ids: string[]) => void;  // replaces all (used by AppInit on load)
  add:    (id: string)    => void;  // optimistic save
  remove: (id: string)    => void;  // optimistic unsave
}

export const useSavedProps = create<SavedPropsStore>((set) => ({
  exact: {},
  changedExact: {},
  setExact: (rows, preserveChanges = false) => set(s => {
    const exact = Object.fromEntries(rows.map(row => [savedSelectionKey(row.prop_id, row.side, row.selection), row.id]));
    if (preserveChanges) for (const key of Object.keys(s.changedExact)) {
      if (s.exact[key]) exact[key] = s.exact[key];
      else delete exact[key];
    }
    return { exact, changedExact: preserveChanges ? s.changedExact : {} };
  }),
  addExact: (key, id) => set(s => ({ exact: { ...s.exact, [key]: id }, changedExact: { ...s.changedExact, [key]: true } })),
  removeExact: key => set(s => { const exact = { ...s.exact }; delete exact[key]; return { exact, changedExact: { ...s.changedExact, [key]: true } }; }),
  ids: {},

  setIds: (ids) =>
    set({
      ids: Object.fromEntries(ids.map((id) => [id, true as const])),
    }),

  add: (id) =>
    set((s) => ({ ids: { ...s.ids, [id]: true } })),

  remove: (id) =>
    set((s) => {
      const next = { ...s.ids };
      delete next[id];
      return { ids: next };
    }),
}));
