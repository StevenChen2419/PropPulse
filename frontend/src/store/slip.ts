import { create } from "zustand";
import type { Prop, PropSide, SelectedOffer, SlipSelection } from "@/lib/types";

// Full Prop objects are stored here because SlipDrawer renders player name,
// prop type, line, and odds directly from items.

interface SlipStore {
  items:      SlipSelection[];
  pendingIds: Record<string, true>;
  changedIds: Record<string, true>;
  loading: boolean;
  loadError: string | null;
  setLoadError: (error: string | null) => void;
  finishLoading: () => void;
  beginMutation: (propId: string) => boolean;
  endMutation: (propId: string) => void;
  initialize: (props: SlipSelection[], preserveChanges?: boolean) => void;
  refreshAvailability: (props: SlipSelection[]) => void;
  addProp:    (prop: Prop, side: PropSide, selection?: SelectedOffer) => void;
  removeProp: (propId: string) => void;
  clear:      () => void;               // local only - caller handles backend
}

export const useSlip = create<SlipStore>((set, get) => ({
  items: [],
  pendingIds: {},
  changedIds: {},
  loading: true,
  loadError: null,
  setLoadError: (loadError) => set({ loadError }),
  finishLoading: () => set({ loading: false }),
  beginMutation: (propId) => {
    if (get().loading || get().loadError || get().pendingIds[propId]) return false;
    set((state) => ({ pendingIds: { ...state.pendingIds, [propId]: true } }));
    return true;
  },
  endMutation: (propId) => set((state) => {
    const pendingIds = { ...state.pendingIds };
    delete pendingIds[propId];
    return { pendingIds };
  }),

  // AppInit preserves local edits when the initial server response arrives late.
  // Keep changed IDs after requests finish so removals cannot be resurrected.
  initialize: (props, preserveChanges = false) => set((state) => preserveChanges ? {
    items: [
      ...props.filter((prop) => !state.changedIds[prop.id]),
      ...state.items.filter((prop) => state.changedIds[prop.id]),
    ],
  } : { items: props, changedIds: {} }),

  // Refresh prices without resurrecting removals or replacing an in-flight choice.
  refreshAvailability: (props) => set((state) => ({
    items: state.items.map((item) => {
      if (state.pendingIds[item.id]) return item;
      const current = props.find((prop) => prop.id === item.id && prop.side === item.side
        && prop.selection?.sportsbook === item.selection?.sportsbook
        && prop.selection?.line === item.selection?.line);
      return current ?? { ...item, selection: item.selection ? { ...item.selection, odds: null, actionable: false } : undefined };
    }),
  })),

  addProp: (prop, side, selection) =>
    set((state) => ({
      changedIds: { ...state.changedIds, [prop.id]: true },
      items: state.items.some((p) => p.id === prop.id)
        ? state.items.map((item) => item.id === prop.id ? { ...prop, side, selection } : item)
        : [...state.items, { ...prop, side, selection }],
    })),

  removeProp: (propId) =>
    set((state) => ({
      changedIds: { ...state.changedIds, [propId]: true },
      items: state.items.filter((p) => p.id !== propId),
    })),

  // Clears local selections only; callers remain responsible for persistence.
  clear: () => set({ items: [] }),
}));
