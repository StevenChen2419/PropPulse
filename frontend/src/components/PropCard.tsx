"use client";
import { requireSession } from "@/store/auth";
import { useOfferClock } from "@/lib/useOfferClock";
import { useRef, useState } from "react";
import Link         from "next/link";
import { useRouter } from "next/navigation";
import { ThumbsUp, ThumbsDown, Bookmark, BookmarkCheck, Plus, Check } from "lucide-react";
import type { Prop, PropSide, SelectedOffer } from "@/lib/types";
import { chooseOffer, getSideOffers, sameOffer, retainedOffer, formatOdds, availabilityLabel, isActionable } from "@/lib/propSides";
import { SportsbookComparison } from "./SportsbookComparison";
import { SaveExactSelection } from "./SaveExactSelection";
import { PropSideComparison } from "./PropSideComparison";
import { OddsStatus, StatisticsStatus } from '@/components/DataStatus';
import { RiskBadge }      from "./RiskBadge";
import { FatigueBar }     from "./FatigueBar";
import { useSlip }        from "@/store/slip";
import { useSavedProps }  from "@/store/savedProps";
import { api }            from "@/lib/api";
import { formatGameContext, propResearchHref } from "@/lib/gameNavigation";

function formatPropType(propType: string): string {
  const labels: Record<string, string> = {
    pra: "PRA",
    rbis: "RBIs",
    total_bases: "Total bases",
    home_runs: "Home runs",
    pass_yds: "Passing yards",
    rush_yds: "Rushing yards",
    reception_yds: "Receiving yards",
    anytime_td: "Touchdowns",
    shots_on_goal: "Shots on goal",
  };
  return labels[propType] ?? propType.replace(/_/g, " ");
}

function formatTime(iso?: string): string {
  if (!iso) return "Today";
  try {
    const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(iso) ? iso : `${iso}Z`;
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return "Today";

    const easternDate = new Intl.DateTimeFormat("en-CA", {
      dateStyle: "short",
      timeZone: "America/New_York",
    }).format(date);
    const todayEastern = new Intl.DateTimeFormat("en-CA", {
      dateStyle: "short",
      timeZone: "America/New_York",
    }).format(new Date());
    const time = new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
      timeZone: "America/New_York",
    }).format(date);

    if (easternDate === todayEastern) {
      return `${time} ET`;
    }

    const dateStr = new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      timeZone: "America/New_York",
    }).format(date);

    return `${dateStr}, ${time} ET`;
  } catch {
    return "Today";
  }
}

function leftBorderClass(label?: string): string {
  switch (label) {
    case "Critical": return "border-l-[3px] border-l-red-400";
    case "High":     return "border-l-[3px] border-l-orange-400";
    case "Medium":   return "border-l-[3px] border-l-amber-400";
    default:         return "border-l-[3px] border-l-transparent";
  }
}

interface Props {
  prop:      Prop;
  // onUnsave is called after a successful unsave API call.
  // Only the Saved page passes this so it can remove the card from its list.
  // The feed page does not pass this prop.
  onUnsave?: () => void;
  onExactChange?: () => void;
}

export function PropCard({ prop, onUnsave, onExactChange }: Props) {
  const router = useRouter();
  useOfferClock();

  // Like/dislike are session-only (not persisted). They record the signal
  // to the backend but do not cause a parent reload.
  const [actionError, setActionError] = useState<string | null>(null);
  const [savingBookmark, setSavingBookmark] = useState(false);
  const bookmarkPending = useRef(false);
  const [liked,    setLiked]    = useState(false);
  const [disliked, setDisliked] = useState(false);

  // Save state is read from the store, which is hydrated from the backend
  // by AppInit on page load.
  const isSaved         = useSavedProps((s) => prop.id in s.ids);
  const addToSaved      = useSavedProps((s) => s.add);
  const removeFromSaved = useSavedProps((s) => s.remove);

  // Slip state is read from the store, which is hydrated from the backend
  // by AppInit on page load.
  const slipItem = useSlip((s) => s.items.find((p) => p.id === prop.id));
  const [chosenSide, setChosenSide] = useState<PropSide | null>(null);
  const selectedSide = chosenSide ?? slipItem?.side ?? (getSideOffers(prop, "over").length ? "over" : "under");
  const [chosenOffer, setChosenOffer] = useState<SelectedOffer | undefined>();
  const resolvedOffer = chooseOffer(prop, selectedSide, chosenOffer ?? (slipItem?.side === selectedSide ? slipItem.selection : undefined))
    ?? retainedOffer(prop, chosenOffer)
    ?? (slipItem?.side === selectedSide ? { ...(slipItem.selection ?? { sportsbook: slipItem.sportsbook, line: slipItem.line }), odds: null, actionable: false } : undefined);
  const selectedOffer = resolvedOffer && isActionable(resolvedOffer, prop.game_time) ? resolvedOffer : resolvedOffer ? { ...resolvedOffer, odds: null } : undefined;
  const sideOffers = getSideOffers(prop, selectedSide);
  const retainedUnavailable = selectedOffer && !sideOffers.some(offer => sameOffer(offer, selectedOffer));
  const slipBusy = useSlip((s) => Boolean(s.pendingIds[prop.id]));
  const slipLoading = useSlip((s) => s.loading);
  const slipLoadError = useSlip((s) => s.loadError);
  const [slipError, setSlipError] = useState<string | null>(null);
  const inSlip = slipItem?.side === selectedSide && Boolean(selectedOffer && sameOffer(selectedOffer, slipItem.selection ?? slipItem));
  const addToSlip  = useSlip((s) => s.addProp);
  const removeSlip = useSlip((s) => s.removeProp);

  const requireAuth = async (): Promise<boolean> => {
    try {
      if (await requireSession()) return true;
      router.push("/login");
    } catch { setActionError("Account temporarily unavailable. Please retry."); }
    return false;
  };

  // Like - updates local state and sends signal to backend.
  // Does NOT call onUnsave or any parent callback.
  // The feed does not need to reload when the user likes a prop.
  const handleLike = async () => {
    if (!await requireAuth()) return;
    setActionError(null);
    setLiked(true);
    setDisliked(false);
    try {
      await api.interact(prop.id, "like");
    } catch {
      setLiked(false); setActionError("Could not record your feedback. Try again."); // roll back on error
    }
  };

  // Dislike - same pattern as like, no parent callback.
  const handleDislike = async () => {
    if (!await requireAuth()) return;
    setActionError(null);
    setDisliked(true);
    setLiked(false);
    try {
      await api.interact(prop.id, "dislike");
    } catch {
      setDisliked(false); setActionError("Could not record your feedback. Try again.");
    }
  };

  // Save/unsave toggle.
  // On save: updates store, calls backend. No parent callback needed.
  // On unsave: updates store, calls backend, then calls onUnsave?.() so
  //   the Saved page can reload its list and remove this card.
  const handleSave = async () => {
    if (bookmarkPending.current || !await requireAuth()) return;
    bookmarkPending.current = true;
    setSavingBookmark(true);
    setActionError(null);
    try {
      if (isSaved) {
        removeFromSaved(prop.id); // optimistic
        try {
          await api.unsave(prop.id);
          onUnsave?.(); // notify Saved page to reload
        } catch {
          addToSaved(prop.id); setActionError("Could not remove your bookmark. Try again."); // roll back
        }
      } else {
        addToSaved(prop.id); // optimistic
        try {
          await api.interact(prop.id, "save");
          // No onUnsave call here - we only notify parent on unsave
        } catch {
          removeFromSaved(prop.id); setActionError("Could not save this prop. Try again."); // roll back
        }
      }
    } finally { bookmarkPending.current = false; setSavingBookmark(false); }
  };

  // Slip add/remove toggle.
  // Updates store and calls backend. No parent callback.
  // SlipDrawer reads from the store directly.
  const handleSlip = async () => {
    if (slipBusy || (!inSlip && selectedOffer?.odds == null) || !await requireAuth()) return;
    const previous = slipItem;
    if (!useSlip.getState().beginMutation(prop.id)) return;
    setSlipError(null);
    if (inSlip) removeSlip(prop.id);
    else addToSlip(prop, selectedSide, selectedOffer);
    try {
      if (inSlip) await api.removeFromSlip(prop.id);
      else {
        const response = await api.interact(prop.id, "add_to_slip", selectedSide, selectedOffer);
        if (response.selection) addToSlip(prop, selectedSide, response.selection);
      }
    } catch (error: unknown) {
      if (previous) addToSlip(previous, previous.side, previous.selection);
      else removeSlip(prop.id);
      setSlipError(error instanceof Error ? error.message : "Could not update your slip. Please try again.");
    } finally {
      useSlip.getState().endMutation(prop.id);
    }
  };

  const bestFor = (side: PropSide) => {
    const best = prop[`best_${side}`];
    return best && getSideOffers(prop, side).some(o => sameOffer(o, best) && o.odds === best.odds) ? best : null;
  };
  const bestOver = bestFor('over'), bestUnder = bestFor('under');
  const showBestLines = bestOver != null || bestUnder != null;

  return (
    <div
      className={`prop-card ${leftBorderClass(
        prop.fatigue?.fatigue_label
      )}`}
    >
      <OddsStatus offer={selectedOffer ?? { ...prop, actionable: false }} gameTime={prop.game_time} />
      <StatisticsStatus coverage={prop.statistics_coverage} />
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="min-w-0 flex-1 mr-3">
          <p className="eyebrow">{prop.player.sport} · {prop.player.team_abbr}</p>
          <Link
            href={propResearchHref(prop.player.id, prop.id, { sportsbook: selectedOffer?.sportsbook ?? prop.sportsbook, line: selectedOffer?.line ?? prop.line, side: selectedSide })}
            className="font-semibold text-gray-900 hover:text-blue-600 transition-colors"
          >
            {prop.player.name}
          </Link>
          <p className="text-xs leading-relaxed text-gray-400 mt-0.5">
            {prop.event_id ? formatGameContext(prop) : <>{prop.player.team_abbr} / {prop.is_home ? "Home" : "Away"} vs {prop.opponent} / {formatTime(prop.game_time)}</>}
          </p>
        </div>
        <div className="flex-shrink-0">
          <RiskBadge fatigue={prop.fatigue} />
        </div>
      </div>

      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">{formatPropType(prop.prop_type)}</p>

      </div>
      <PropSideComparison prop={prop} selectedSide={selectedSide} selection={selectedOffer} busy={slipBusy} onSelect={(side) => { setChosenSide(side); setChosenOffer(chooseOffer(prop, side, selectedOffer) ?? chooseOffer(prop, side)); setSlipError(null); }} />
      <label className="mb-3 block text-xs font-medium text-gray-600">
        Sportsbook for your pick
        <select aria-label={`Sportsbook for ${prop.player.name} ${selectedSide}`} disabled={slipBusy || !sideOffers.length}
          value={selectedOffer ? JSON.stringify([selectedOffer.sportsbook, selectedOffer.line]) : ""}
          onChange={(event) => { setChosenOffer(sideOffers.find((offer) => JSON.stringify([offer.sportsbook, offer.line]) === event.target.value)); setSlipError(null); }}
          className="mt-1 w-full rounded-lg border border-gray-200 bg-white p-2 text-sm text-gray-800 disabled:opacity-50">
          {retainedUnavailable && <option value={JSON.stringify([selectedOffer.sportsbook, selectedOffer.line])} disabled>{selectedOffer.sportsbook} · {selectedSide === "over" ? "Over" : "Under"} {selectedOffer.line} · Unavailable (saved selection)</option>}
          {!sideOffers.length && !retainedUnavailable && <option value="">No available prices</option>}
          {sideOffers.map((offer) => <option key={JSON.stringify([offer.sportsbook, offer.line])} value={JSON.stringify([offer.sportsbook, offer.line])}>
            {offer.sportsbook} · {selectedSide === "over" ? "Over" : "Under"} {offer.line} · {formatOdds(offer.odds)}
            {sameOffer(offer, prop[`best_${selectedSide}`] ?? { sportsbook: "", line: 0 }) ? " · Best line" : ""}
          </option>)}
        </select>
      </label>

      {/* Best available sportsbook prices */}
      {showBestLines && (
        <div className="mb-3 border-y border-gray-100 py-2.5">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-600">Best prices · line {prop.line}</p>
            <p className="text-xs text-gray-400">
              {prop.sportsbook_count} sportsbooks
            </p>
          </div>
          <div className="grid grid-cols-2 divide-x divide-gray-100">
            <div className="pr-3">
              <p className="text-xs text-gray-400">Over</p>
              {bestOver ? (
                <p className="mt-0.5 truncate text-xs font-medium text-gray-700">
                  {bestOver.sportsbook}{" "}
                  <span className={bestOver.odds > 0 ? "text-emerald-600" : ""}>
                    {formatOdds(bestOver.odds)}
                  </span>{" "}
                  <span className="text-gray-400">at {bestOver.line}</span>
                </p>
              ) : (
                <p className="mt-0.5 text-xs text-gray-400">Not available</p>
              )}
            </div>
            <div className="pl-3">
              <p className="text-xs text-indigo-600">Under</p>
              {bestUnder ? (
                <p className="mt-0.5 truncate text-xs font-medium text-gray-700">
                  {bestUnder.sportsbook}{" "}
                  <span className="text-indigo-600">
                    {formatOdds(bestUnder.odds)}
                  </span>{" "}
                  <span className="text-gray-400">at {bestUnder.line}</span>
                </p>
              ) : (
                <p className="mt-0.5 text-xs text-gray-400">Not available</p>
              )}
            </div>
          </div>
        </div>
      )}

      <SaveExactSelection propId={prop.id} side={selectedSide} selection={selectedOffer} onChange={onExactChange} />
      <SportsbookComparison comparison={prop.comparison} side={selectedSide} line={selectedOffer?.line ?? prop.line}
        sportsbook={selectedOffer?.sportsbook} gameTime={prop.game_time} busy={slipBusy || slipLoading}
        onSelect={(offer, side) => { setChosenOffer(offer); setChosenSide(side); }} />

      {/* Fatigue bar */}
      {prop.fatigue && (
        <div className="mb-3">
          <FatigueBar fatigue={prop.fatigue} />
        </div>
      )}

      {/* Reason chips */}
      {prop.reasons && prop.reasons.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {prop.reasons.map((reason, i) => (
            <span
              key={i}
              className="text-xs bg-blue-50 text-blue-600 border border-blue-100 px-2 py-0.5 rounded-full"
            >
              {reason}
            </span>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-3 border-t border-gray-50">
        <div className="flex gap-1">
          <button
            onClick={handleLike}
            aria-label={`Like ${prop.player.name} prop`}
            aria-pressed={liked}
            title="Like"
            className={`p-2 rounded-lg transition-all ${
              liked
                ? "bg-blue-100 text-blue-700"
                : "text-gray-400 hover:text-blue-600 hover:bg-blue-50"
            }`}
          >
            <ThumbsUp size={15} />
          </button>

          <button
            onClick={handleDislike}
            aria-label={`Not interested in ${prop.player.name} prop`}
            aria-pressed={disliked}
            title="Not interested"
            className={`p-2 rounded-lg transition-all ${
              disliked
                ? "bg-red-100 text-red-700"
                : "text-gray-400 hover:text-red-500 hover:bg-red-50"
            }`}
          >
            <ThumbsDown size={15} />
          </button>

          <button
            onClick={handleSave}
            disabled={savingBookmark}
            aria-busy={savingBookmark}
            aria-label={isSaved ? "Remove bookmark" : "Save for later"}
            aria-pressed={isSaved}
            title={isSaved ? "Remove bookmark" : "Save for later"}
            className={`p-2 rounded-lg transition-all ${
              isSaved
                ? "bg-amber-100 text-amber-700"
                : "text-gray-400 hover:text-amber-600 hover:bg-amber-50"
            }`}
          >
            {isSaved ? <BookmarkCheck size={15} /> : <Bookmark size={15} />}
          </button>
        </div>

        <button
          onClick={handleSlip}
          disabled={slipLoading || Boolean(slipLoadError) || slipBusy || (!inSlip && selectedOffer?.odds == null)}
          aria-busy={slipLoading || slipBusy}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold text-[#ffffff] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:opacity-40 disabled:cursor-not-allowed ${
            selectedSide === "over"
              ? "bg-emerald-700 hover:bg-emerald-800 focus-visible:ring-emerald-600"
              : "bg-indigo-600 hover:bg-[#3a5487] focus-visible:ring-indigo-600"
          }`}
        >
          {inSlip ? <Check size={12} /> : <Plus size={12} />}
          {slipLoading ? "Loading slip..." : slipBusy ? "Updating..." : inSlip ? `Remove ${selectedSide === "over" ? "Over" : "Under"} from Slip` : `${slipItem ? "Switch to" : "Add"} ${selectedSide === "over" ? "Over" : "Under"} ${slipItem ? "in" : "to"} Slip`}
        </button>
      </div>

      {actionError && <p role="alert" className="mt-2 rounded-lg bg-red-50 p-2 text-xs text-red-700">{actionError}</p>}
      {slipError && <p role="alert" className="mt-2 rounded-lg bg-red-50 p-2 text-xs text-red-700">{slipError}</p>}
      {slipLoadError && <p className="mt-2 text-xs text-muted">Retry loading your research slip before changing selections.</p>}
      {!inSlip && selectedOffer?.odds == null && <p className="mt-2 text-xs text-muted">No available price for this selection. Historical research and bookmarks remain available.</p>}

      {/* Footer */}
      <div className="flex justify-between items-center mt-2">
        <span className="text-xs text-gray-400">{selectedOffer?.sportsbook ?? prop.sportsbook}</span>
        <Link href={propResearchHref(prop.player.id, prop.id, { sportsbook: selectedOffer?.sportsbook ?? prop.sportsbook, line: selectedOffer?.line ?? prop.line, side: selectedSide })} className="inline-flex min-h-11 items-center text-xs font-semibold text-blue-500">Research &rarr;</Link>
        {prop.discover_score != null ? (
          <span className="text-xs font-medium text-blue-500">
            Over research {Math.round(prop.discover_score)}
          </span>
        ) : prop.rank_score != null ? (
          <span className="text-xs text-gray-300">
            Match {Math.round(prop.rank_score * 100)}%
          </span>
        ) : null}
      </div>
    </div>
  );
}
