import type {
  Prop,
  SavedSelection,
  PropSide,
  SelectedOffer,
  ParlayEstimate,
  ParlayEstimateRequest,
  User,
  UserPreferences,
  Slip,
  PlayerDetail,
  PlayerGameLog,
  InteractionAction,
  FatigueData,
  InsightsData,
  ModelStatus,
  OddsIngestionStatus,
  TodayGame,
  GameDetail,
  DiscoverResponse,
  PlayerResearch,
  PlayerSearchResponse,
  SportRiskIntelligenceData,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); this.name = "ApiError"; }
}

let csrfToken: string | null = null;
let csrfRequest: Promise<string> | null = null;
let csrfGeneration = 0;

export function invalidateCsrf() { csrfToken = null; csrfRequest = null; csrfGeneration += 1; }

async function getCsrf(): Promise<string> {
  if (csrfToken) return csrfToken;
  if (!csrfRequest) {
    const generation = csrfGeneration;
    csrfRequest = request<{ csrf_token: string }>("/auth/csrf").then(result => {
      if (!result.csrf_token) throw new Error("Could not verify request security. Please retry.");
      if (generation === csrfGeneration) csrfToken = result.csrf_token;
      return result.csrf_token;
    }).finally(() => { if (generation === csrfGeneration) csrfRequest = null; });
  }
  return csrfRequest;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  const method = (options.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers["X-CSRF-Token"] = await getCsrf();

  const res = await fetch(`${BASE}${path}`, { ...options, credentials: "include", cache: "no-store", headers });

  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event("proppulse:unauthorized"));
    if (res.status === 403) invalidateCsrf();
    let detail = `Request failed (${res.status})`;
    try {
      const err = await res.json();
      detail = typeof err.detail === "string" ? err.detail : detail;
    } catch {
      // keep default
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

export const api = {
  // Auth
  login: async (email: string, password: string) => {
    const result = await request<{ ok: boolean }>("/auth/login", {
      method: "POST",
      body:   JSON.stringify({ email, password }),
    });
    invalidateCsrf(); return result;
  },

  register: async (email: string, password: string, username?: string) => {
    const result = await request<{ ok: boolean }>("/auth/register", {
      method: "POST",
      body:   JSON.stringify({ email, password, username }),
    });
    invalidateCsrf(); return result;
  },

  logout: async () => {
    const result = await request<{ ok: boolean }>("/auth/logout", { method: "POST" });
    invalidateCsrf(); return result;
  },

  // Feed
  getFeed: (params?: {
    limit?:     number;
    offset?:    number;
    sport?:     string;
    prop_type?: string;
    game_key?:  string;
    event_id?:  string;
  }, signal?: AbortSignal) => {
    const qs = new URLSearchParams();
    if (params?.limit)     qs.set("limit",     String(params.limit));
    if (params?.offset)    qs.set("offset",    String(params.offset));
    if (params?.sport)     qs.set("sport",     params.sport);
    if (params?.prop_type) qs.set("prop_type", params.prop_type);
    if (params?.game_key)  qs.set("game_key",  params.game_key);
    if (params?.event_id)  qs.set("event_id",  params.event_id);
    return request<{ props: Prop[]; total: number; refreshed_at?: string | null }>(
      `/props/feed?${qs.toString()}`, { signal }
    );
  },

  getGames: (params?: { sport?: string; limit?: number }, signal?: AbortSignal) => {
    const qs = new URLSearchParams();
    if (params?.sport) qs.set("sport", params.sport);
    if (params?.limit) qs.set("limit", String(params.limit));
    return request<TodayGame[]>(`/props/todays-games?${qs.toString()}`, { signal });
  },

  getGame: (identity: string | { event_id?: string; game_key?: string; sport?: string }, signal?: AbortSignal) => {
    const params = typeof identity === "string" ? { game_key: identity } : identity;
    const qs = new URLSearchParams();
    if (params.event_id) qs.set("event_id", params.event_id);
    if (params.game_key) qs.set("game_key", params.game_key);
    if (params.sport) qs.set("sport", params.sport);
    return request<GameDetail>(`/props/game?${qs.toString()}`, { signal });
  },

  getDiscover: (params?: {
    sport?: string;
    prop_type?: string;
    game_key?: string;
    event_id?: string;
    limit?: number;
    offset?: number;
    browse?: boolean;
    search?: string;
    sportsbook?: string;
    game_date?: string;
    availability?: string;
    sort?: string;
  }, signal?: AbortSignal) => {
    const qs = new URLSearchParams();
    if (params?.sport) qs.set("sport", params.sport);
    if (params?.prop_type) qs.set("prop_type", params.prop_type);
    if (params?.game_key) qs.set("game_key", params.game_key);
    if (params?.event_id) qs.set("event_id", params.event_id);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    if (params?.browse) qs.set("browse", "true");
    for (const key of ['search', 'sportsbook', 'game_date', 'availability', 'sort'] as const) {
      if (params?.[key]) qs.set(key, params[key]);
    }
    return request<DiscoverResponse>(`/props/discover?${qs.toString()}`, { signal });
  },

  // Interactions
  interact: (propId: string, action: InteractionAction, side?: PropSide, selection?: Pick<SelectedOffer, "sportsbook" | "line">) =>
    request<{ ok: boolean; action: string; selection?: SelectedOffer }>(`/interactions/${propId}`, {
      method: "POST",
      body:   JSON.stringify({ action, ...(side ? { side } : {}), ...(selection ? { sportsbook: selection.sportsbook, line: selection.line } : {}) }),
    }),

  unsave: (propId: string) =>
    request<{ ok: boolean }>(`/interactions/${propId}/save`, {
      method: "DELETE",
    }),

  removeFromSlip: (propId: string) =>
    request<{ ok: boolean }>(`/interactions/slip/${propId}`, {
      method: "DELETE",
    }),

  // Players
  getPlayer: (playerId: string, signal?: AbortSignal) =>
    request<PlayerDetail>(`/players/${playerId}`, { signal }),

  getPlayerFatigue: (playerId: string) =>
    request<FatigueData>(`/players/${playerId}/fatigue`),

  // Returns last 10 game log entries from game_logs.csv matched by player name.
  // Games array is empty when CSV does not exist; note field explains why.
  getPlayerGameLog: (playerId: string, signal?: AbortSignal) =>
    request<PlayerGameLog>(`/players/${playerId}/game-log`, { signal }),

  getPlayerResearch: (
    playerId: string,
    params?: { prop_id?: string; prop_type?: string; line?: number; season?: string; competition?: string;
      sportsbook?: string; offer_line?: number; side?: string },
    signal?: AbortSignal,
  ) => {
    const qs = new URLSearchParams();
    if (params?.prop_id) qs.set("prop_id", params.prop_id);
    if (params?.prop_type) qs.set("prop_type", params.prop_type);
    if (params?.line != null) qs.set("line", String(params.line));
    if (params?.season) qs.set("season", params.season);
    if (params?.competition) qs.set("competition", params.competition);
    if (params?.sportsbook) qs.set('sportsbook', params.sportsbook);
    if (params?.offer_line != null) qs.set('offer_line', String(params.offer_line));
    if (params?.side) qs.set('side', params.side);
    return request<PlayerResearch>(
      `/players/${playerId}/research?${qs.toString()}`, { signal }
    );
  },

  searchPlayers: (params?: { q?: string; sport?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.q) qs.set("q", params.q);
    if (params?.sport) qs.set("sport", params.sport);
    if (params?.limit) qs.set("limit", String(params.limit));
    return request<PlayerSearchResponse>(`/players/search?${qs.toString()}`);
  },

  getPlayerWatchlist: () =>
    request<PlayerSearchResponse>("/players/watchlist"),

  followPlayer: (playerId: string) =>
    request<{ ok: boolean; following: boolean }>(`/players/${playerId}/follow`, {
      method: "POST",
    }),

  unfollowPlayer: (playerId: string) =>
    request<{ ok: boolean; following: boolean }>(`/players/${playerId}/follow`, {
      method: "DELETE",
    }),

  // Users
  getMe: (signal?: AbortSignal) => request<User>("/users/me", { signal }),

  updatePreferences: (prefs: Partial<UserPreferences>) =>
    request<{ ok: boolean }>("/users/me/preferences", {
      method: "PUT",
      body:   JSON.stringify(prefs),
    }),

  getSaved: () => request<{ saved: Prop[]; selections: SavedSelection[] }>("/users/me/saved"),

  saveSelection: (propId: string, side: PropSide, selection: Pick<SelectedOffer, "sportsbook" | "line">) =>
    request<{ id: string }>(`/users/me/saved/selections/${propId}`, {
      method: "POST", body: JSON.stringify({ sportsbook: selection.sportsbook, line: selection.line, side }),
    }),

  deleteSavedSelection: (id: string) => request<{ ok: boolean }>(`/users/me/saved/selections/${id}`, { method: "DELETE" }),

  addSavedSelectionToSlip: (id: string) => request<{ selection: SelectedOffer }>(`/users/me/saved/selections/${id}/slip`, { method: "POST" }),

  editSlipSelection: (propId: string, side: PropSide, selection: Pick<SelectedOffer, "sportsbook" | "line">) =>
    request<{ id: string; selection: SelectedOffer }>(`/users/me/slip/items/${propId}`, {
      method: "PATCH", body: JSON.stringify({ sportsbook: selection.sportsbook, line: selection.line, side }),
    }),

  getSlip: () => request<{ slip: Slip | null }>("/users/me/slip"),

  estimateParlay: (body: ParlayEstimateRequest, signal?: AbortSignal) =>
    request<ParlayEstimate>("/users/me/slip/estimate", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    }),

  // Rankings
  getRiskIntelligence: (sport?: string, signal?: AbortSignal) =>
    request<SportRiskIntelligenceData>(
      `/rankings/risk-intelligence${sport ? `?${new URLSearchParams({ sport })}` : ""}`,
      { signal },
    ),

  getFatigueLeaderboard: () => request<any[]>("/rankings/fatigue-leaderboard"),

  getInsights: () => request<InsightsData>("/rankings/insights"),

  getModelStatus: () => request<ModelStatus>("/rankings/model-status"),

  getIngestionStatus: () =>
    request<OddsIngestionStatus>("/props/ingestion-status"),
};
