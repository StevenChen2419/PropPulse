"use client";
import type { ComparisonOffer, PropSide, SportsbookComparison as Comparison } from '@/lib/types';
import { formatOdds, isActionable, sameOffer } from '@/lib/propSides';
import { OddsStatus } from '@/components/DataStatus';

export function SportsbookComparison({ comparison, side, line, sportsbook, gameTime, busy = false, onSelect }: {
  comparison?: Comparison | null; side: PropSide; line: number; sportsbook?: string; gameTime?: string;
  busy?: boolean; onSelect: (offer: ComparisonOffer, side: PropSide) => void;
}) {
  if (!comparison) return <p className="my-3 text-xs text-muted">Sportsbook comparison unavailable. You can still research the recorded line.</p>;
  const groups = comparison.groups.filter(g => g.side === side);
  return <details className="my-3 min-w-0 border-y border-gray-100 py-3 text-xs">
    <summary className="cursor-pointer font-medium text-gray-600 focus-visible:ring-2 focus-visible:ring-indigo-400">
      Compare sportsbooks · {side} · {groups.length} line{groups.length === 1 ? '' : 's'}
    </summary>
    <p className="my-2 text-muted">Best prices compare the same line and direction. Last-known prices are research only.</p>
    {!groups.length && <p>No stored sportsbook offers for this selection.</p>}
    {groups.map(group => {
      // The server chooses the winner. A ticking client can withdraw its label,
      // but never promote a different or older offer into a live recommendation.
      const best = group.best && isActionable(group.best, gameTime) ? group.best : null;
      return <section key={group.line} aria-label={`${side} ${group.line} sportsbook comparison`} className="my-3 rounded-lg border border-gray-100 p-2">
        <h3 className="font-semibold capitalize text-gray-800">{side} {group.line} · {group.line === line ? 'Selected line' : 'Alternative line'}</h3>
        <p className="mt-1 text-gray-500">{best ? `Best live price: ${best.sportsbook} ${formatOdds(best.odds)}` : 'No current best price confirmed'}</p>
        {best && group.offers.every(o => !o.actionable || isActionable(o, gameTime)) && group.advantage_per_100 != null && group.advantage_per_100 > 0 && <p className="mt-1 text-muted">${group.advantage_per_100.toFixed(2)} more profit per $100 stake than the next live price on this line.</p>}
        {group.offers.map(offer => {
          const selected = sportsbook != null && sameOffer(offer, { sportsbook, line });
          const winner = best && sameOffer(best, offer);
          return <div key={offer.sportsbook} className="mt-2 border-t border-gray-100 pt-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0 break-words font-medium text-gray-700" title={offer.provider_bookmaker_key ?? undefined}>{offer.provider_title || offer.sportsbook} · {offer.odds == null ? 'Price unavailable' : formatOdds(offer.odds)}{winner ? ' · Best' : ''}</span>
              <button type="button" disabled={busy} aria-pressed={selected}
                onClick={() => onSelect(offer, side)} className="rounded border border-gray-200 px-2 py-1 text-gray-600 hover:border-indigo-400 disabled:opacity-50">
                {selected ? 'Selected' : 'Use line for research'}
              </button>
            </div>
            <OddsStatus offer={offer} gameTime={gameTime} />
          </div>;
        })}
      </section>;
    })}
  </details>;
}
