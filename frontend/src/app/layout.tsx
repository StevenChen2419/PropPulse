import type { Metadata } from "next";
import "./globals.css";
import { NavBar }    from "@/components/NavBar";
import { SlipDrawer } from "@/components/SlipDrawer";
import { AppInit }   from "@/components/AppInit";


export const metadata: Metadata = {
  title: "PropPulse",
  description: "Player props, historical performance, and matchup research in one workspace",
};

// NO "use client" here — layout.tsx exports metadata and must stay a server component.
// NavBar, SlipDrawer, and AppInit are client components; Next.js handles the boundary.
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50">
        {/* Hydrates savedProps + slip stores from backend on every page load */}
        <AppInit />
        <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-xl focus:bg-surface focus:p-4">Skip to content</a>
        <NavBar />
        <div id="main-content" tabIndex={-1}>{children}</div>
        <SlipDrawer />
      </body>
    </html>
  );
}