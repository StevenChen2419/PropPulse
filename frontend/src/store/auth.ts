import { create } from "zustand";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";
import { useSavedProps } from "@/store/savedProps";
import { useSlip } from "@/store/slip";

type AuthState = {
  status: "unknown" | "authenticated" | "anonymous" | "error";
  user: User | null;
  error: string | null;
};

export const useAuth = create<AuthState>(() => ({ status: "unknown", user: null, error: null }));
let pending: Promise<User | null> | null = null;
let generation = 0;

function clearPersonalState() {
  useSavedProps.setState({ ids: {}, exact: {}, changedExact: {} });
  useSlip.setState({ items: [], pendingIds: {}, changedIds: {}, loading: false, loadError: null });
}

export function clearSession() {
  generation += 1;
  pending = null;
  useAuth.setState({ status: "anonymous", user: null, error: null });
  clearPersonalState();
}

export function restoreSession(): Promise<User | null> {
  if (pending) return pending;
  const current = generation;
  pending = api.getMe().then(user => {
    if (current === generation) {
      const previousUser = useAuth.getState().user;
      if (previousUser && previousUser.id !== user.id) clearPersonalState();
      useAuth.setState({ status: "authenticated", user, error: null });
    }
    return current === generation ? user : null;
  }).catch(error => {
    if (current !== generation) return null;
    if (error instanceof ApiError && error.status === 401) { clearSession(); return null; }
    useAuth.setState({ status: useAuth.getState().user ? "authenticated" : "error", error: "Account temporarily unavailable. Please retry." });
    throw error;
  }).finally(() => { if (current === generation) pending = null; });
  return pending;
}

export async function requireSession(): Promise<boolean> {
  const { status } = useAuth.getState();
  if (status === "authenticated") return true;
  if (status === "anonymous") return false;
  return Boolean(await restoreSession());
}

export async function signOut() {
  await api.logout();
  clearSession();
}
