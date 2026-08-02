import { createContext, useContext, type ReactNode } from "react";

const FeedbackContext = createContext<(() => void) | null>(null);

export function FeedbackProvider({
  openFeedback,
  children,
}: {
  openFeedback: () => void;
  children: ReactNode;
}) {
  return <FeedbackContext.Provider value={openFeedback}>{children}</FeedbackContext.Provider>;
}

export function useFeedback(): () => void {
  const open = useContext(FeedbackContext);
  if (!open) {
    throw new Error("useFeedback must be used within FeedbackProvider");
  }
  return open;
}

/** Returns null outside FeedbackProvider — for optional drawer chrome. */
export function useFeedbackOptional(): (() => void) | null {
  return useContext(FeedbackContext);
}
