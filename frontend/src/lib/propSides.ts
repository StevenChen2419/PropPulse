import type { OfferAvailability, Prop, PropSide, SelectedOffer, SlipSelection } from "./types";

function utcMillis(value?: string | null): number {
  return value ? Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`) : NaN;
}

export function offerObservation(offer: OfferAvailability): string | null | undefined {
  return offer.provider_observed_at === undefined ? offer.refreshed_at : offer.provider_observed_at;
}

export function isActionable(offer: OfferAvailability, gameTime?: string): boolean {
  const now = Date.now();
  const observed = utcMillis(offerObservation(offer));
  return offer.actionable === true && (offer.availability == null || offer.availability === "available") && Number.isFinite(utcMillis(offer.expires_at))
    && Number.isFinite(observed) && observed <= now && now - observed <= 30 * 60000
    && now <= utcMillis(offer.expires_at)
    && Number.isFinite(utcMillis(gameTime)) && now < utcMillis(gameTime);
}

export function availabilityLabel(offer: OfferAvailability, gameTime?: string): string {
  if (offer.availability === "game_started" || (gameTime && utcMillis(gameTime) <= Date.now())) return "Game started";
  const age = Date.now() - utcMillis(offerObservation(offer));
  if (offer.availability === "expired" || (offer.expires_at && utcMillis(offer.expires_at) < Date.now()) || age > 6 * 3600000) return "Expired odds";
  if (age > 30 * 60000 && age <= 6 * 3600000 && offer.availability !== "market_unavailable") return "Last known odds";
  if (!isActionable(offer, gameTime)) return "Market unavailable";
  return age > 30 * 60 * 1000 ? "Last known odds" : "Live odds";
}

export function getSideOdds(prop: Prop, side: PropSide): number | null {
  return getSideOffers(prop, side).find((offer) => sameOffer(offer, prop))?.odds ?? null;
}

export function formatOdds(odds: number | null): string {
  return odds == null ? "—" : odds > 0 ? `+${odds}` : String(odds);
}

export function getSelectionOdds(item: SlipSelection): number | null {
  if (!item.selection || !isActionable(item.selection, item.game_time)) return null;
  const odds = item.selection.odds;
  return typeof odds === "number" && Number.isFinite(odds) && Math.abs(odds) >= 100 ? odds : null;
}

export function getSideOffers(prop: Prop, side: PropSide): SelectedOffer[] {
  return (prop.sportsbook_offers ?? []).flatMap((offer) => {
    const odds = offer[`${side}_odds`];
    return isActionable(offer, prop.game_time) && typeof odds === "number" && Number.isFinite(odds) && Math.abs(odds) >= 100
      ? [{ ...offer, odds }] : [];
  });
}

export function sameOffer(a: Pick<SelectedOffer, "sportsbook" | "line">, b: Pick<SelectedOffer, "sportsbook" | "line">): boolean {
  return a.sportsbook === b.sportsbook && a.line === b.line;
}

export function chooseOffer(prop: Prop, side: PropSide, preferred?: SelectedOffer): SelectedOffer | undefined {
  const offers = getSideOffers(prop, side);
  if (preferred) return offers.find((offer) => sameOffer(offer, preferred));
  return offers.find((offer) => sameOffer(offer, prop)) || offers[0];
}

/** Keep an explicitly chosen identity visible when a refresh removes its price. */
export function retainedOffer(prop: Prop, preferred?: SelectedOffer): SelectedOffer | undefined {
  if (!preferred) return undefined;
  const stored = (prop.sportsbook_offers ?? []).find(o => sameOffer(o, preferred));
  return { ...(stored ?? { ...preferred, availability: 'market_unavailable' as const }), odds: null, actionable: false };
}
