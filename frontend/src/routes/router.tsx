// Route table (Phase 1 plan §5.2, DESIGN §13.1 subset). NOT /compare or
// /compare remains Phase 3.
import { createBrowserRouter, Navigate } from "react-router-dom";

import { LoginPage } from "../auth/LoginPage";
import { AuthCallbackPage } from "../auth/AuthCallbackPage";
import { OnboardingPage } from "../auth/OnboardingPage";
import { ProfilePage } from "../auth/ProfilePage";
import { RequireAuth } from "../auth/RequireAuth";
import { RequireProfile } from "../auth/RequireProfile";
import { ResetPasswordPage } from "../auth/ResetPasswordPage";
import { SignOutPage } from "../auth/SignOutPage";
import { AppLayout } from "../components/AppLayout";
import { ColorsPage } from "../dev/ColorsPage";
import { HuntSwitcherPage } from "../features/hunts/HuntSwitcherPage";
import { HuntSettingsPage } from "../features/hunts/HuntSettingsPage";
import { InviteAcceptPage } from "../features/invites/InviteAcceptPage";
import { InvitationLinkJoinPage } from "../features/invites/InvitationLinkJoinPage";
import { OverviewPage } from "../features/listings/OverviewPage";
import { TasksPage } from "../features/jobs/TasksPage";
import { RubricPage } from "../features/rubric/RubricPage";

const authenticatedRoute = (element: React.ReactNode) => <RequireAuth>{element}</RequireAuth>;
const protectedRoute = (element: React.ReactNode) => authenticatedRoute(<RequireProfile>{element}</RequireProfile>);
// Deliberately omitted when Vite builds for production. Removing the color lab
// permanently is one component file plus this small route block.
const developmentRoutes = import.meta.env.DEV
  ? [{ path: "/colors", element: <ColorsPage /> }]
  : [];

export const router = createBrowserRouter([
  ...developmentRoutes,
  { path: "/login", element: <LoginPage /> },
  { path: "/signout", element: <SignOutPage /> },
  { path: "/auth/callback", element: <AuthCallbackPage /> },
  { path: "/auth/reset-password", element: authenticatedRoute(<ResetPasswordPage />) },
  { path: "/onboarding", element: authenticatedRoute(<OnboardingPage />) },
  { path: "/profile", element: protectedRoute(<ProfilePage />) },
  { path: "/invite/:token", element: protectedRoute(<InviteAcceptPage />) },
  { path: "/join/:token", element: protectedRoute(<InvitationLinkJoinPage />) },
  {
    path: "/",
    element: protectedRoute(<HuntSwitcherPage />),
  },
  {
    path: "/h/:huntId",
    element: protectedRoute(<AppLayout />),
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "rubric", element: <RubricPage /> },
      { path: "tasks", element: <TasksPage /> },
      { path: "settings", element: <HuntSettingsPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
