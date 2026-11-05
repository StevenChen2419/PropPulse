"use client";
import { useEffect, useState } from "react";

/** Reevaluate observation expiry and game start even while offline. */
export function useOfferClock() {
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);
}
