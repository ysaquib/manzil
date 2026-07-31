// Per-Visit Presence (VC-5, DESIGN §13.3) — the app's first Presence channel.
//
// Scoped to the Visit route rather than held hunt-wide: presence only means
// something while several people are walking the same apartment, and a channel
// held open across the whole app would report "here" for someone who closed the
// tab three screens ago.
//
// Ambient by design (§9.7): this feeds an avatar row and one quiet line. It
// never blocks, never prompts, and is not the storage path for anything — the
// checklist has to work with no signal at all.
import { useEffect, useMemo, useRef, useState } from "react";

import type { RealtimeChannel } from "@supabase/supabase-js";

import { supabase } from "../../lib/supabase";

export interface PresentMember {
  userId: string;
  /** The section they are looking at, when they have opened one. */
  sectionKey: string | null;
  /** Milliseconds since the epoch, from the joiner's own clock. Display only. */
  onlineAt: number;
}

interface PresenceState {
  user_id: string;
  section_key: string | null;
  online_at: number;
}

type Listener = (present: PresentMember[]) => void;

interface Shared {
  channel: RealtimeChannel;
  userId: string;
  listeners: Set<Listener>;
  /** Latest computed roster, so a late subscriber gets it without a round trip. */
  present: PresentMember[];
  /**
   * The section to report. Latched here rather than closed over, because the
   * consumer knows its section before the channel finishes joining — reading it
   * at SUBSCRIBED time is what makes the first broadcast say "in Kitchen"
   * instead of a bare "here".
   */
  sectionKey: string | null;
  /** The section last actually broadcast. */
  trackedSection?: string | null;
  /** Serialises re-tracking, so a fast series of section changes cannot interleave. */
  pending?: Promise<void>;
  /** Pending teardown, cancelled if the route is re-entered first. */
  release?: ReturnType<typeof setTimeout>;
}

/**
 * Exactly one channel per Visit, shared by every mounted consumer.
 *
 * This is not an optimisation. supabase-js keys channels by topic and refuses
 * new callbacks after `subscribe()`, so the obvious "drop the stale channel and
 * open a fresh one" remount handling opens a *second* channel that tracks under
 * the same presence key while the first is still joined server-side — two live
 * sockets claiming to be the same person, only one of which any given teardown
 * closes. One channel, ref-counted, is the fix: a remount reuses it rather than
 * racing it.
 */
const shared = new Map<string, Shared>();

/**
 * How long a channel outlives its last consumer. React StrictMode mounts,
 * unmounts and remounts effects back to back in development, and a route can be
 * re-entered just as fast; tearing down synchronously would recreate the very
 * race this module exists to avoid. Long enough to absorb that, short enough
 * that leaving the Visit really does drop you off the roster.
 */
const RELEASE_DELAY_MS = 250;

function computePresent(channel: RealtimeChannel, viewerId: string): PresentMember[] {
  const state = channel.presenceState<PresenceState>();
  const present: PresentMember[] = [];
  for (const [key, entries] of Object.entries(state)) {
    // "You are here" is not news — the row is about who else showed up.
    if (key === viewerId) continue;
    // One member can have two tabs open; the newest wins so the section shown
    // is the one they are actually looking at.
    const newest = [...entries].sort((a, b) => b.online_at - a.online_at)[0];
    if (!newest) continue;
    present.push({
      userId: newest.user_id ?? key,
      sectionKey: newest.section_key ?? null,
      onlineAt: newest.online_at ?? 0,
    });
  }
  present.sort((a, b) => a.onlineAt - b.onlineAt);
  return present;
}

/**
 * Move this member to `entry.sectionKey`, replacing their presence rather than
 * adding to it.
 *
 * The untrack is load-bearing, not tidiness. `track()` *appends* a meta for the
 * key and `untrack()` removes only one, so tracking twice — which happens on
 * every ordinary mount, since the section is known only after the checklist
 * loads — strands a meta that no teardown can reach. The member then shows as
 * present forever after they leave. Replacing costs a sub-second blink in other
 * people's avatar rows; presence is ambient, a permanently wrong roster is not.
 */
function retrack(entry: Shared, userId: string) {
  entry.pending = (entry.pending ?? Promise.resolve())
    .then(async () => {
      const section = entry.sectionKey;
      if (entry.trackedSection === section) return;
      if (entry.channel.state !== "joined") return;
      await entry.channel.untrack();
      entry.trackedSection = section;
      await entry.channel.track({
        user_id: userId,
        section_key: section,
        online_at: Date.now(),
      } satisfies PresenceState);
    })
    .catch(() => undefined);
}

function acquire(
  visitId: string,
  userId: string,
  sectionKey: string | null,
  listener: Listener,
): Shared {
  const key = `${visitId}:${userId}`;
  const existing = shared.get(key);
  if (existing) {
    if (existing.release) {
      clearTimeout(existing.release);
      existing.release = undefined;
    }
    existing.listeners.add(listener);
    listener(existing.present);
    return existing;
  }

  const channel = supabase.channel(`visit:${visitId}`, {
    config: { presence: { key: userId } },
  });
  const entry: Shared = {
    channel,
    userId,
    listeners: new Set([listener]),
    present: [],
    sectionKey,
  };
  shared.set(key, entry);

  const sync = () => {
    entry.present = computePresent(channel, userId);
    for (const notify of entry.listeners) notify(entry.present);
  };

  channel
    .on("presence", { event: "sync" }, sync)
    .on("presence", { event: "join" }, sync)
    .on("presence", { event: "leave" }, sync)
    .subscribe((status) => {
      if (status === "SUBSCRIBED") {
        entry.trackedSection = entry.sectionKey;
        void channel.track({
          user_id: userId,
          section_key: entry.sectionKey,
          online_at: Date.now(),
        } satisfies PresenceState);
      }
    });

  return entry;
}

function release(visitId: string, userId: string, listener: Listener) {
  const key = `${visitId}:${userId}`;
  const entry = shared.get(key);
  if (!entry) return;
  entry.listeners.delete(listener);
  if (entry.listeners.size > 0) return;

  entry.release = setTimeout(() => {
    if (entry.listeners.size > 0) return;
    shared.delete(key);
    // untrack before removing: it states the departure outright rather than
    // leaving the other clients to infer it from a socket close.
    void entry.channel
      .untrack()
      .catch(() => undefined)
      .finally(() => {
        void supabase.removeChannel(entry.channel);
      });
  }, RELEASE_DELAY_MS);
}

/**
 * Who else is in this Visit right now, and where.
 *
 * Returns everyone **except** the viewer.
 */
export function useVisitPresence(
  visitId: string | undefined,
  userId: string | undefined,
  sectionKey: string | null,
): PresentMember[] {
  const [others, setOthers] = useState<PresentMember[]>([]);
  // Read at join time without making the section a subscribe dependency.
  const sectionKeyRef = useRef(sectionKey);
  sectionKeyRef.current = sectionKey;

  useEffect(() => {
    if (!visitId || !userId) {
      setOthers([]);
      return;
    }
    const listener: Listener = (present) => setOthers(present);
    acquire(visitId, userId, sectionKeyRef.current, listener);
    return () => {
      release(visitId, userId, listener);
    };
    // `sectionKey` is deliberately not a dependency: re-subscribing on every
    // section change would make this member flicker out and back in for
    // everyone else. The effect below re-tracks on the live channel instead.
  }, [visitId, userId]);

  useEffect(() => {
    if (!visitId || !userId) return;
    const entry = shared.get(`${visitId}:${userId}`);
    if (!entry) return;
    entry.sectionKey = sectionKey;
    // Still joining: the SUBSCRIBED handler will pick the section up from the
    // latch above, so there is nothing to send yet.
    if (entry.channel.state !== "joined") return;
    retrack(entry, userId);
  }, [visitId, userId, sectionKey]);

  return useMemo(() => others, [others]);
}
