// The invitation round trip: click a link while signed out, sign in, and land
// back on the invitation rather than on the homepage.
//
// These drive the real guards (`RequireAuth`, `RequireProfile`) against a real
// `MemoryRouter`, because every previous break in this flow was a routing
// break — a lost target, a guard that fired in the wrong order — and a test of
// the pages alone would have caught none of them.
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { MemoryRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthContext } from "../src/auth/AuthProvider";
import { LoginPage } from "../src/auth/LoginPage";
import { RequireAuth } from "../src/auth/RequireAuth";
import { RequireProfile } from "../src/auth/RequireProfile";
import { AuthCallbackPage } from "../src/auth/AuthCallbackPage";
import { renderWithProviders } from "./testUtils";

const auth = vi.hoisted(() => ({
  signInWithOtp: vi.fn().mockResolvedValue({ error: null }),
  signInWithPassword: vi.fn().mockResolvedValue({ error: null }),
  verifyOtp: vi.fn().mockResolvedValue({ error: null }),
  resetPasswordForEmail: vi.fn().mockResolvedValue({ error: null }),
}));
vi.mock("../src/lib/supabase", () => ({ supabase: { auth } }));

const profile = vi.hoisted(() => ({ data: undefined as unknown, isLoading: false }));
vi.mock("../src/auth/profile", () => ({ useProfile: () => profile }));

const SESSION = { user: { id: "u1", email: "member@example.com" } };

/** Prints the current location so a test can assert where the flow ended up. */
function Whereami() {
  const location = useLocation();
  return <div data-testid="where">{`${location.pathname}${location.search}`}</div>;
}

// The signing-in half of `AuthProvider`, which the mocked Supabase client
// stands in for: a successful call flips the context to a session, exactly as
// `onAuthStateChange` would, so the guard re-evaluates on the new route.
let signIn: ((session: typeof SESSION | null) => void) | null = null;

function Harness({ initial, children }: { initial: typeof SESSION | null; children: ReactNode }) {
  const [session, setSession] = useState(initial);
  signIn = setSession;
  return (
    <AuthContext.Provider value={{ session: session as never, loading: false }}>
      {children}
    </AuthContext.Provider>
  );
}

function renderFlow({
  entry,
  session,
}: {
  entry: string;
  session: typeof SESSION | null;
}) {
  const guarded = (node: ReactNode) => (
    <RequireAuth>
      <RequireProfile>{node}</RequireProfile>
    </RequireAuth>
  );
  return renderWithProviders(
    <MemoryRouter initialEntries={[entry]}>
      <Harness initial={session}>
        <Whereami />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="/onboarding" element={<div>ONBOARDING</div>} />
          <Route path="/invite/:token" element={guarded(<div>INVITE PAGE</div>)} />
          <Route path="/join/:token" element={guarded(<div>JOIN PAGE</div>)} />
          <Route path="/" element={guarded(<div>HOME</div>)} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Harness>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  profile.data = { user_id: "u1" };
  profile.isLoading = false;
  sessionStorage.clear();
  signIn = null;
  auth.signInWithPassword.mockImplementation(async () => {
    act(() => signIn?.(SESSION));
    return { error: null };
  });
});

afterEach(() => sessionStorage.clear());

describe("an invitation link clicked while signed out", () => {
  it("sends you to the login page carrying the invitation as ?next=", () => {
    renderFlow({ entry: "/invite/tok-1", session: null });

    expect(screen.getByTestId("where")).toHaveTextContent(
      "/login?next=%2Finvite%2Ftok-1",
    );
    // And says why you are here, rather than showing a bare sign-in form.
    expect(screen.getByText("Sign in to accept your invitation")).toBeInTheDocument();
  });

  it("does the same for a reusable Invitation Link", () => {
    renderFlow({ entry: "/join/tok-2", session: null });
    expect(screen.getByTestId("where")).toHaveTextContent("/login?next=%2Fjoin%2Ftok-2");
  });

  it("returns to the invitation after a password sign-in", async () => {
    const user = userEvent.setup();
    renderFlow({ entry: "/invite/tok-1", session: null });

    await user.type(screen.getByLabelText("Email"), "member@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    // The page navigates on success; the guard then renders the invitation
    // because this render's context already carries a session.
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent("/invite/tok-1"),
    );
  });

  it("points the magic link at a callback that knows where to return", async () => {
    const user = userEvent.setup();
    renderFlow({ entry: "/join/tok-2", session: null });

    await user.click(screen.getByText("Magic link"));
    await user.type(screen.getByLabelText("Email"), "member@example.com");
    await user.click(screen.getByRole("button", { name: "Send magic link" }));

    expect(auth.signInWithOtp).toHaveBeenCalledWith({
      email: "member@example.com",
      options: expect.objectContaining({
        emailRedirectTo: expect.stringContaining("next=%2Fjoin%2Ftok-2"),
        shouldCreateUser: false,
      }),
    });
  });

  it("carries the invitation through a password reset too", async () => {
    const user = userEvent.setup();
    renderFlow({ entry: "/invite/tok-1", session: null });

    await user.type(screen.getByLabelText("Email"), "member@example.com");
    await user.click(screen.getByRole("button", { name: "Forgot password?" }));

    expect(auth.resetPasswordForEmail).toHaveBeenCalledWith(
      "member@example.com",
      expect.objectContaining({
        redirectTo: expect.stringContaining("/auth/reset-password?next=%2Finvite%2Ftok-1"),
      }),
    );
  });

  it("lands a signed-in visitor on the login page straight back at the invitation", () => {
    renderFlow({ entry: "/login?next=%2Finvite%2Ftok-1", session: SESSION });
    expect(screen.getByTestId("where")).toHaveTextContent("/invite/tok-1");
  });
});

describe("the magic-link callback", () => {
  it("resumes the invitation named in ?next=", async () => {
    renderFlow({ entry: "/auth/callback?next=%2Finvite%2Ftok-1", session: SESSION });
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent("/invite/tok-1"),
    );
  });

  it("refuses a target that is not an invitation, however it got into the URL", async () => {
    renderFlow({ entry: "/auth/callback?next=%2F%2Fevil.example", session: SESSION });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/"));
    expect(screen.getByText("HOME")).toBeInTheDocument();
  });
});

describe("a first-time account", () => {
  it("completes onboarding with the invitation still attached", () => {
    profile.data = undefined;
    renderFlow({ entry: "/invite/tok-1", session: SESSION });

    expect(screen.getByTestId("where")).toHaveTextContent(
      "/onboarding?next=%2Finvite%2Ftok-1",
    );
  });
});

describe("a demo visitor", () => {
  it("reaches the invitation page instead of being bounced to sign in", () => {
    // Exactly what `enterDemo` leaves behind: a server-minted token and no
    // GoTrue session at all.
    const claims = btoa(
      JSON.stringify({ sub: "demo", manzil_demo: true, exp: Math.floor(Date.now() / 1000) + 600 }),
    );
    sessionStorage.setItem("manzil-demo-token", `header.${claims}.signature`);

    renderFlow({ entry: "/invite/tok-1", session: null });

    expect(screen.getByText("INVITE PAGE")).toBeInTheDocument();
  });
});
