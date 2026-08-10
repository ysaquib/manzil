import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthContext } from "../src/auth/AuthProvider";
import { LoginPage } from "../src/auth/LoginPage";
import { renderWithProviders } from "./testUtils";

const auth = vi.hoisted(() => ({
  signInWithOtp: vi.fn().mockResolvedValue({ error: null }),
  signInWithPassword: vi.fn().mockResolvedValue({ error: null }),
  verifyOtp: vi.fn().mockResolvedValue({ error: null }),
  resetPasswordForEmail: vi.fn().mockResolvedValue({ error: null }),
}));

vi.mock("../src/lib/supabase", () => ({ supabase: { auth } }));

function renderLogin() {
  return renderWithProviders(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthContext.Provider value={{ session: null, loading: false }}>
        <LoginPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe("LoginPage account creation boundary", () => {
  beforeEach(() => vi.clearAllMocks());

  it("does not offer public registration", () => {
    renderLogin();

    expect(screen.queryByRole("button", { name: /register|create account/i })).toBeNull();
    expect(screen.getByText(/account created by an administrator/i)).toBeInTheDocument();
  });

  it("requests magic links for existing accounts only", async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByText("Magic link"));
    await user.type(screen.getByLabelText("Email"), "member@example.com");
    await user.click(screen.getByRole("button", { name: "Send magic link" }));

    expect(auth.signInWithOtp).toHaveBeenCalledWith({
      email: "member@example.com",
      options: expect.objectContaining({ shouldCreateUser: false }),
    });
  });
});

// Enter is how people finish a login form. Reaching for the mouse after typing
// a password is the kind of small wrongness that makes an app feel unfinished.
describe("LoginPage keyboard submission", () => {
  beforeEach(() => vi.clearAllMocks());

  it("signs in on Enter from the password field", async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Email"), "member@example.com");
    await user.type(screen.getByLabelText("Password"), "hunter2{Enter}");

    expect(auth.signInWithPassword).toHaveBeenCalledWith({
      email: "member@example.com",
      password: "hunter2",
    });
  });

  it("sends the magic link on Enter from the email field", async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByText("Magic link"));
    await user.type(screen.getByLabelText("Email"), "member@example.com{Enter}");

    expect(auth.signInWithOtp).toHaveBeenCalledOnce();
  });

  it("does not submit an incomplete form", async () => {
    const user = userEvent.setup();
    renderLogin();

    // Email only, in password mode: Enter must not fire a credential-less
    // sign-in the disabled button would have refused.
    await user.type(screen.getByLabelText("Email"), "member@example.com{Enter}");

    expect(auth.signInWithPassword).not.toHaveBeenCalled();
  });

  it("verifies the emailed code on Enter", async () => {
    const user = userEvent.setup();
    renderLogin();

    await user.click(screen.getByText("Magic link"));
    await user.type(screen.getByLabelText("Email"), "member@example.com{Enter}");

    const codeField = await screen.findByLabelText("Email code");
    await user.type(codeField, "123456{Enter}");

    expect(auth.verifyOtp).toHaveBeenCalledWith({
      email: "member@example.com",
      token: "123456",
      type: "email",
    });
  });
});
