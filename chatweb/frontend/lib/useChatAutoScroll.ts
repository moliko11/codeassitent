"use client";

import { useEffect, useRef } from "react";

/**
 * Pins a streaming chat surface to the bottom while new content arrives,
 * unless the user has scrolled up to read history.
 *
 * Ported concept from DeepTutor's useChatAutoScroll: the scroll container
 * carries `data-chat-scroll-root="true"` (see globals.css) so the browser's
 * own scroll anchoring doesn't fight this pin.
 *
 * Usage:
 *   const scrollRef = useChatAutoScroll([messages.length, streamingContent]);
 *   <div ref={scrollRef} data-chat-scroll-root="true" className="overflow-y-auto">
 */
export function useChatAutoScroll(deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);

  // Track whether the user is near the bottom.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      pinnedRef.current = distanceFromBottom < 80;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // Re-pin to bottom whenever a dependency changes (new message / new token).
  useEffect(() => {
    const el = ref.current;
    if (!el || !pinnedRef.current) return;
    el.scrollTop = el.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return ref;
}
