const window = { games: 5, observed_games: 5, average_minutes: 34, date_start: '2026-10-02T23:00:00Z', date_end: '2026-10-10T23:00:00Z', seasons: [2027], insufficient_sample: false };
function restWorkload(propId = null, eventId = null) {
  return {
    status: 'available', player_id: 'fixture-player', sport: 'NBA', classification: 'observed_and_derived', evaluated_at: '2026-10-11T17:00:00Z',
    reference: { at: '2026-10-11T23:00:00Z', source: eventId ? 'event' : 'as_of', event_id: eventId, prop_id: propId },
    coverage: { stored_games: 13, eligible_games: 10, excluded_counts: { duplicate_game: 1, future_game: 1, unsupported_source: 1 },
      date_start: '2026-09-20T23:00:00Z', date_end: window.date_end, sources: ['espn_nba'], schedule_complete: false,
      notes: ['Completion is inferred from prior-date provider statistics.', 'Counts are lower bounds; missed games and travel are unknown.'] },
    rest: { days_since_last_game: 1, back_to_back: true, category: 'back_to_back', games_in_7d: 3, games_in_14d: 6, schedule_density: 0.429,
      classification: 'derived', explanation: '1 Eastern calendar day = back-to-back; 2 = short rest; 3+ = extended rest. Density = recorded games in 7 days / 7.' },
    workload: { l5: { ...window }, l10: { ...window, games: 9, observed_games: 10, average_minutes: 32, seasons: [2026, 2027], insufficient_sample: true },
      season: { ...window, games: 6, observed_games: 6, average_minutes: 33 }, l5_vs_season: 1, minutes_trend: null, variability: 3.2, missing_minutes: 1,
      explanation: 'L5 minus season is minutes/game; trend is last 5 minus preceding 5. Variability is population standard deviation of L10.' },
    rest_splits: [{ category: 'back_to_back', games: 2, minutes_games: 1, average_minutes: 30, points_games: 2, average_points: 22, date_start: window.date_start, date_end: window.date_end }],
    interpretation: { classification: 'heuristic', label: 'Descriptive workload context', explanation: 'Rest categories describe retained appearance gaps.', experimental_model_used: false },
  };
}
module.exports = { restWorkload };
function verifiedRest(overrides = {}) {
  return {
    status: 'confirmed', reference_at: '2026-10-11T23:00:00Z', provenance: ['Fixture final summaries', 'Fixture complete box scores'],
    context_team_id: 'fixture-team', evidence_counts: { games: 3, participation: 3, membership: 1, coverage: 1, excluded_conflicts: 0, excluded_invalid: 0 },
    last_confirmed_appearance: { status: 'confirmed', game_id: 'fixture-appearance', team_id: 'fixture-team', game_at: '2026-10-08T23:00:00Z', completed_at: '2026-10-09T01:30:00Z', gap_days: 3, full_rest_days: 2 },
    last_completed_team_game: { status: 'confirmed', game_id: 'fixture-team-final', team_id: 'fixture-team', game_at: '2026-10-10T23:00:00Z', completed_at: '2026-10-11T01:30:00Z', gap_days: 1, full_rest_days: 0 },
    team_back_to_back: true, confirmed_missed_games: 1, partial_missed_games_lower_bound: 1, dnp_games: 1, inactive_games: 0,
    unknown_participation_games: 0, uncovered_games: 0, schedule_complete: true,
    notes: ['Fixture evidence covers final team games and explicit appearances or non-appearances.'], ...overrides,
  };
}
module.exports.verifiedRest = verifiedRest;
function nbaVerifiedRest() {
  const verified = verifiedRest({ status: 'partial',
    provenance: ['NBA.com PlayerGameLog', 'NBA.com LeagueGameLog'],
    confirmed_missed_games: null, partial_missed_games_lower_bound: null,
    context_team_id: null, last_completed_team_game: null, team_back_to_back: null,
    dnp_games: 0, inactive_games: 0, schedule_complete: false,
    notes: ['Fixture NBA.com observations do not prove complete participation coverage.'],
  });
  verified.last_confirmed_appearance = { ...verified.last_confirmed_appearance,
    provider: 'nba_com', game_id: '0022500001', team_id: '1610612738', status: 'partial', time_precision: 'eastern_date' };
  return verified;
}
module.exports.nbaVerifiedRest = nbaVerifiedRest;
