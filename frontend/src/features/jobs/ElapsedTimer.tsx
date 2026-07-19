// Counting-up m:ss (h:mm:ss past an hour) since a timestamp — the "is it
// actually moving?" signal on running job cards. Re-renders once a second.
import { Text } from "@mantine/core";
import { useEffect, useState } from "react";

export function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const mm = String(minutes).padStart(hours > 0 ? 2 : 1, "0");
  const ss = String(seconds).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function ElapsedTimer({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <Text size="xs" c="dimmed" ff="monospace" style={{ fontVariantNumeric: "tabular-nums" }} span>
      {formatElapsed(now - new Date(since).getTime())}
    </Text>
  );
}
