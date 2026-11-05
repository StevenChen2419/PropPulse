import { gameQuery } from '@/lib/gameNavigation';

export const DISCOVER_SPORTS = ['NBA', 'WNBA', 'MLB', 'NFL', 'NHL'];
export const DISCOVER_SORTS = [
  ['upcoming', 'Upcoming game'], ['player', 'Player name A–Z'], ['market', 'Market / line ↑'],
  ['over_desc', 'Best Over price ↓'], ['over_asc', 'Best Over price ↑'],
  ['under_desc', 'Best Under price ↓'], ['under_asc', 'Best Under price ↑'],
] as const;
export const DISCOVER_PAGE_SIZE = 24;
export interface DiscoverFilters {
  sport: string; market: string; search: string; sportsbook: string; game_date: string;
  availability: string; sort: string; page: number; game: string;
}

export function readDiscoverFilters(params: Pick<URLSearchParams, 'get'>): DiscoverFilters {
  const sport = params.get('sport')?.toUpperCase() ?? '';
  const sort = params.get('sort') ?? 'upcoming';
  const availability = params.get('availability') ?? '';
  const day = params.get('game_date') ?? '';
  const page = Number(params.get('page') || 1);
  const event = params.get('event_id') ?? '';
  const legacy = params.get('game_key') ?? '';
  const market = params.get('market') ?? params.get('prop_type') ?? '';
  return {
    sport: DISCOVER_SPORTS.includes(sport) ? sport : '',
    market: /^[a-z0-9_]{1,60}$/.test(market) ? market : '',
    search: (params.get('search') ?? '').replace(/\s+/g, ' ').trim().slice(0, 120),
    sportsbook: (params.get('sportsbook') ?? '').slice(0, 80),
    game_date: /^\d{4}-\d{2}-\d{2}$/.test(day) && !isNaN(Date.parse(day)) && new Date(day).toISOString().startsWith(day) ? day : '',
    availability: ['available', 'last_known'].includes(availability) ? availability : '',
    sort: DISCOVER_SORTS.some(([key]) => key === sort) ? sort : 'upcoming',
    page: Number.isInteger(page) && page > 0 && page <= 41667 ? page : 1,
    game: /^[0-9a-f-]{36}$/i.test(event) ? `event:${event}` : legacy.includes('|') && legacy.length <= 500 ? `legacy:${legacy}` : '',
  };
}

export function discoverURL(filters: DiscoverFilters): string {
  const params = new URLSearchParams();
  for (const key of ['sport', 'market', 'search', 'sportsbook', 'game_date', 'availability'] as const) {
    if (filters[key]) params.set(key, filters[key]);
  }
  for (const [key, value] of Object.entries(gameQuery(filters.game))) params.set(key, value);
  if (filters.sort !== 'upcoming') params.set('sort', filters.sort);
  if (filters.page > 1) params.set('page', String(filters.page));
  return `/discover${params.size ? `?${params}` : ''}`;
}
