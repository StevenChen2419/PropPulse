"use client";
import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Menu, X, Activity, Layers } from "lucide-react";

import { useAuth, restoreSession, signOut as endSession } from "@/store/auth";

const NAV_LINKS = [
  { href: "/",          label: "Board"    },
  { href: "/discover",  label: "Discover" },
  { href: "/players",   label: "Players" },
  { href: "/analytics", label: "Insights"    },
  { href: "/saved",     label: "Saved"   },
  { href: "/profile",   label: "Account" },
];

export function NavBar() {
  const userEmail = useAuth(s => s.user?.email ?? null);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [mounted,   setMounted]   = useState(false);
  const [menuOpen,  setMenuOpen]  = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape" && menuOpen) { setMenuOpen(false); menuButton.current?.focus(); } };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [menuOpen]);
  const pathname = usePathname();
  const router   = useRouter();

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  useEffect(() => { void restoreSession().catch(() => {}); }, [pathname]);

  const signOut = async () => {
    if (signingOut) return;
    setSigningOut(true); setLogoutError(null);
    try { await endSession(); router.push("/login"); }
    catch { setLogoutError("Could not sign out. Please retry."); }
    finally { setSigningOut(false); }
  };

  const userInitial  = userEmail ? userEmail[0].toUpperCase() : null;

  const links = (mobile = false) => NAV_LINKS.map(({ href, label }) => {
    const active = pathname === href || (href === "/players" && pathname.startsWith("/player/"));
    return <Link key={href} href={href} aria-current={active ? "page" : undefined}
      className={`flex min-h-11 items-center rounded-xl px-3 text-sm font-medium transition-colors ${active ? "bg-blue-50 text-blue-500" : "text-muted hover:bg-raised hover:text-ink"} ${mobile ? "w-full" : ""}`}>{label}</Link>;
  });
  const toggleMenu = () => {
    if (!menuOpen) window.dispatchEvent(new Event("proppulse:collapse-slip"));
    setMenuOpen(open => !open);
  };
  const openSlip = () => { window.dispatchEvent(new Event("proppulse:open-slip")); setMenuOpen(false); };
  return (
    <nav aria-label="Main navigation" className="sticky top-0 z-40 border-b border-gray-100 bg-canvas/95 backdrop-blur-md">
      <div className="mx-auto flex h-[76px] max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5" aria-label="PropPulse home">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-blue-200 bg-blue-50 text-blue-500"><Activity size={21} /></span>
          <span className="text-lg font-bold tracking-tight text-ink">PropPulse<span className="hidden text-[9px] font-medium uppercase tracking-[.22em] text-muted sm:block">Sports research</span></span>
        </Link>
        <div className="hidden items-center gap-1 xl:flex">{links()}<button onClick={openSlip} className="button ml-2"><Layers size={15} />Research slip</button></div>
        <div className="flex items-center gap-2">
          {mounted && <div className="hidden items-center gap-3 sm:flex">{userEmail ? <><Link href="/profile" title={`Signed in as ${userEmail}`} className="flex h-10 w-10 items-center justify-center rounded-full border border-blue-100 bg-blue-50 text-sm font-bold text-blue-500">{userInitial}</Link><button disabled={signingOut} onClick={signOut} className="text-xs text-muted hover:text-ink">Sign out</button></> : <Link href="/login" className="button button-primary">Sign in</Link>}</div>}
          <button ref={menuButton} type="button" onClick={toggleMenu} aria-label={menuOpen ? "Close navigation" : "Open navigation"} aria-expanded={menuOpen} aria-controls="mobile-navigation" className="button !px-3 xl:hidden">{menuOpen ? <X size={20} /> : <Menu size={20} />}</button>
        </div>
      </div>
      {menuOpen && <div id="mobile-navigation" className="max-h-[calc(100dvh-76px)] overflow-y-auto border-t border-gray-100 bg-surface px-4 py-4 shadow-float xl:hidden"><div className="mx-auto grid max-w-6xl grid-cols-2 gap-2">{links(true)}<button onClick={openSlip} className="button justify-start"><Layers size={16} />Research slip</button></div>{mounted && <div className="mx-auto mt-3 flex max-w-6xl items-center justify-between gap-3 border-t border-gray-100 pt-3">{userEmail ? <><span className="min-w-0 truncate text-xs text-muted">{userEmail}</span><button disabled={signingOut} onClick={signOut} className="button">Sign out</button></> : <Link href="/login" className="button button-primary">Sign in</Link>}</div>}</div>}
      {logoutError && <p role="alert" className="px-4 pb-2 text-xs text-red-600">{logoutError}</p>}
    </nav>
  );
}
