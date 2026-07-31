import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// A miniature stand-in for a Realtime channel, faithful to the one behaviour
// that made this hook hard to get right: `track()` *appends* a presence meta and
// `untrack()` removes them all. Tracking twice without untracking therefore
// strands a meta the teardown can never reach, and the member shows as present
// forever after they leave. Every assertion below exists because that shipped.
class FakeChannel {
  topic: string;
  state = "closed";
  metas: { section_key: string | null }[] = [];
  handlers: Record<string, (() => void)[]> = {};
  untrackCount = 0;
  private key: string;

  constructor(topic: string, key: string) {
    this.topic = topic;
    this.key = key;
  }

  on(_type: string, opts: { event: string }, cb: () => void) {
    (this.handlers[opts.event] ??= []).push(cb);
    return this;
  }

  subscribe(cb: (status: string) => void) {
    this.state = "joined";
    cb("SUBSCRIBED");
    return this;
  }

  async track(payload: { section_key: string | null }) {
    this.metas.push(payload);
    this.emit("sync");
    return "ok";
  }

  async untrack() {
    this.untrackCount += 1;
    this.metas = [];
    this.emit("sync");
    return "ok";
  }

  presenceState() {
    return this.metas.length ? { [this.key]: this.metas } : {};
  }

  private emit(event: string) {
    for (const cb of this.handlers[event] ?? []) cb();
  }
}

let channels: FakeChannel[] = [];
const removed: FakeChannel[] = [];

vi.mock("../src/lib/supabase", () => ({
  supabase: {
    channel: (name: string, opts: { config: { presence: { key: string } } }) => {
      const channel = new FakeChannel(`realtime:${name}`, opts.config.presence.key);
      channels.push(channel);
      return channel;
    },
    removeChannel: async (channel: FakeChannel) => {
      removed.push(channel);
      channel.state = "closed";
      return "ok";
    },
    getChannels: () => channels,
  },
}));

const { useVisitPresence } = await import("../src/features/visits/usePresence");

describe("useVisitPresence", () => {
  beforeEach(() => {
    channels = [];
    removed.length = 0;
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  it("opens exactly one channel for a Visit, however often the effect remounts", async () => {
    const { unmount } = renderHook(() => useVisitPresence("v-one", "me", null));
    const { unmount: unmount2 } = renderHook(() => useVisitPresence("v-one", "me", null));
    await waitFor(() => expect(channels).toHaveLength(1));
    unmount();
    unmount2();
  });

  it("replaces its presence rather than stacking metas when the section changes", async () => {
    const { rerender } = renderHook(({ section }) => useVisitPresence("v-two", "me", section), {
      initialProps: { section: null as string | null },
    });
    await waitFor(() => expect(channels).toHaveLength(1));
    const channel = channels[0]!;

    const sections = () => channel.metas.map((meta) => meta.section_key);

    rerender({ section: "kitchen" });
    await waitFor(() => expect(sections()).toEqual(["kitchen"]));

    rerender({ section: "noise" });
    await waitFor(() => expect(sections()).toEqual(["noise"]));

    // The regression: without the untrack, this would be three stacked metas and
    // the single untrack on teardown would leave two behind.
    expect(channel.metas).toHaveLength(1);
  });

  it("untracks before dropping the channel, so others see the leave", async () => {
    const { unmount } = renderHook(() => useVisitPresence("v-three", "me", "kitchen"));
    await waitFor(() => expect(channels).toHaveLength(1));
    const channel = channels[0]!;

    unmount();
    await act(async () => {
      vi.advanceTimersByTime(400);
      await Promise.resolve();
    });

    await waitFor(() => expect(removed).toContain(channel));
    expect(channel.untrackCount).toBeGreaterThan(0);
    expect(channel.metas).toHaveLength(0);
  });

  it("keeps the channel when the route is re-entered before the release lands", async () => {
    const first = renderHook(() => useVisitPresence("v-four", "me", null));
    await waitFor(() => expect(channels).toHaveLength(1));
    first.unmount();

    // Back inside the release window — a StrictMode remount, or a fast
    // back-navigation. Reopening the channel here is what used to leave two
    // sockets claiming to be the same person.
    const second = renderHook(() => useVisitPresence("v-four", "me", null));
    await act(async () => {
      vi.advanceTimersByTime(400);
      await Promise.resolve();
    });

    expect(channels).toHaveLength(1);
    expect(removed).toHaveLength(0);
    second.unmount();
  });

  it("reports everyone except the viewer", async () => {
    const { result } = renderHook(() => useVisitPresence("v-five", "me", null));
    await waitFor(() => expect(channels).toHaveLength(1));
    const channel = channels[0]!;

    // The viewer's own key is the only one this fake tracks, so presence stays
    // empty: "you are here" is not news.
    expect(result.current).toEqual([]);
    expect(channel.metas).toHaveLength(1);
  });
});
