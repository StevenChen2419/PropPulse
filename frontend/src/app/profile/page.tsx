"use client";
import { useEffect, useState } from "react";
import { useRouter }   from "next/navigation";
import { AlertCircle } from "lucide-react";
import { PageHeading } from "@/components/Workspace";
import { useAuth, restoreSession, signOut } from "@/store/auth";
import { api }         from "@/lib/api";
import type { User }   from "@/lib/types";

const SPORTS: string[] = ["NBA", "WNBA", "NFL", "MLB", "NHL", "NCAAB", "NCAAF"];

const PROP_TYPES: string[] = [
  "points", "assists", "rebounds", "threes", "pra",
  "blocks", "steals", "touchdowns", "rushing yards", "receiving yards",
];

type SaveStatus = "idle" | "saving" | "saved" | "error";

export default function ProfilePage() {
  const router = useRouter();
  const authStatus = useAuth(s => s.status);
  useEffect(() => { if (authStatus === "anonymous") router.push("/login"); }, [authStatus, router]);
  const [user,      setUser]      = useState<User | null>(null);
  const [sports,    setSports]    = useState<string[]>([]);
  const [propTypes, setPropTypes] = useState<string[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [status,    setStatus]    = useState<SaveStatus>("idle");

  useEffect(() => {
    restoreSession()
      .then((u) => {
        if (!u) { router.push("/login"); return; }
        setUser(u);
        setSports(u.fav_sports     ?? []);
        setPropTypes(u.fav_prop_types ?? []);
      })
      .catch((e: unknown) => {
        const message =
          e instanceof Error ? e.message : "Could not load profile.";
        setLoadError(message);
      })
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = (
    arr:    string[],
    val:    string,
    setter: (v: string[]) => void
  ) => {
    setter(
      arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]
    );
  };

  const handleSave = async () => {
    setStatus("saving");
    try {
      await api.updatePreferences({
        fav_sports:     sports,
        fav_prop_types: propTypes,
      });
      setStatus("saved");
      // Brief pause so the user sees the success state, then redirect to feed.
      setTimeout(() => {
        router.push("/");
        router.refresh();
      }, 900);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
    }
  };

  const handleSignOut = async () => {
    setLogoutError(null);
    try { await signOut(); router.push("/login"); }
    catch { setLogoutError("Could not sign out. Please retry."); }
  };

  // Loading skeleton
  if (loading) {
    return (
      <main className="min-h-screen bg-gray-50">
        <div className="workspace space-y-4">
          {[80, 120, 160].map((h) => (
            <div
              key={h}
              className="bg-white rounded-2xl border border-gray-100 animate-pulse"
              style={{ height: h }}
            />
          ))}
        </div>
      </main>
    );
  }

  // Load error
  if (loadError || !user) {
    return (
      <main className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="text-center">
          <AlertCircle size={32} className="text-red-300 mx-auto mb-3" />
          <p className="font-medium text-gray-700">Could not load profile</p>
          <p className="text-sm text-gray-400 mt-1 mb-4">
            {loadError || "Unknown error"}
          </p>
          {logoutError && <p role="alert">{logoutError}</p>}
          <button
            onClick={() => router.push("/login")}
            className="text-sm text-blue-600 hover:underline"
          >
            Sign in again
          </button>
        </div>
      </main>
    );
  }

  const buttonLabel: Record<SaveStatus, string> = {
    idle:   "Save preferences",
    saving: "Saving...",
    saved:  "Saved - loading your personalized feed...",
    error:  "Error saving - try again",
  };

  const buttonStyle: Record<SaveStatus, string> = {
    idle:   "bg-blue-600 text-[#ffffff] hover:bg-[#1b6656]",
    saving: "bg-gray-400 text-white cursor-not-allowed",
    saved:  "bg-emerald-500 text-white",
    error:  "bg-red-500 text-white",
  };

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="workspace !max-w-3xl">

        <PageHeading eyebrow="Your account" title="Research preferences" description="Personalize your board and manage your account." />
        {/* User card */}
        <div className="bg-white rounded-2xl border border-gray-100 p-5 mb-5">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-bold text-lg flex-shrink-0">
              {user.email[0].toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-gray-900">
                {user.username || "PropPulse User"}
              </p>
              <p className="text-sm text-gray-400 truncate">{user.email}</p>
            </div>
          </div>
        </div>

        {/* Personalization explanation */}
        <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 mb-4">
          <p className="text-xs font-semibold text-blue-700 mb-0.5">
            How preferences affect your feed
          </p>
          <p className="text-xs text-blue-600 leading-snug">
            Sports you select weight 30% of each prop's score.
            Prop types you select weight an additional 15%.
            Saving these preferences re-ranks the feed immediately.
          </p>
        </div>

        {/* Sports selector */}
        <div className="bg-white rounded-2xl border border-gray-100 p-5 mb-4">
          <h2 className="font-semibold text-gray-800 mb-1">
            Favorite sports
          </h2>
          <p className="text-xs text-gray-400 mb-3">
            Props from selected sports rank higher in your feed.
          </p>
          <div className="flex flex-wrap gap-2">
            {SPORTS.map((s) => (
              <button
                key={s}
                aria-pressed={sports.includes(s)}
                onClick={() => toggle(sports, s, setSports)}
                className={`px-3 py-1.5 rounded-full text-sm font-medium transition-all border ${
                  sports.includes(s)
                    ? "bg-blue-600 text-[#ffffff] border-gray-900"
                    : "bg-white text-gray-500 border-gray-200 hover:border-gray-400"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
          {sports.length === 0 && (
            <p className="text-xs text-amber-600 mt-2">
              Select at least one sport to personalize your feed
            </p>
          )}
        </div>

        {/* Prop types selector */}
        <div className="bg-white rounded-2xl border border-gray-100 p-5 mb-5">
          <h2 className="font-semibold text-gray-800 mb-1">
            Favorite prop types
          </h2>
          <p className="text-xs text-gray-400 mb-3">
            Props matching these types rank higher regardless of sport.
          </p>
          <div className="flex flex-wrap gap-2">
            {PROP_TYPES.map((pt) => (
              <button
                key={pt}
                aria-pressed={propTypes.includes(pt)}
                onClick={() => toggle(propTypes, pt, setPropTypes)}
                className={`px-3 py-1.5 rounded-full text-sm font-medium transition-all border capitalize ${
                  propTypes.includes(pt)
                    ? "bg-blue-600 text-[#ffffff] border-blue-600"
                    : "bg-white text-gray-500 border-gray-200 hover:border-gray-400"
                }`}
              >
                {pt}
              </button>
            ))}
          </div>
        </div>

        {/* Save button */}
        <button
          onClick={handleSave}
          disabled={status === "saving" || status === "saved"}
          className={`w-full py-3 rounded-xl text-sm font-semibold transition-all ${buttonStyle[status]}`}
        >
          {buttonLabel[status]}
        </button>

        {logoutError && <p role="alert" className="mt-3 text-sm text-red-600">{logoutError}</p>}
        {/* Sign out */}
        <button
          onClick={handleSignOut}
          className="w-full mt-3 py-2.5 rounded-xl text-sm text-gray-400 hover:text-red-500 border border-gray-100 hover:border-red-200 transition-colors"
        >
          Sign out
        </button>

      </div>
    </main>
  );
}
