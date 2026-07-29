// Route table (DESIGN §13.1 subset — /compare landed with P3-13's compare half).
import { createBrowserRouter, Navigate } from "react-router-dom";

import { LoginPage } from "../auth/LoginPage";
import { AuthCallbackPage } from "../auth/AuthCallbackPage";
import { OnboardingPage } from "../auth/OnboardingPage";
import { AccountPage } from "../auth/AccountPage";
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
import { ComparePage } from "../features/listings/ComparePage";
import { OverviewPage } from "../features/listings/OverviewPage";
import { HuntMapPage } from "../features/map/HuntMapPage";
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
  // /profile was the pre-P3-16 account surface; keep it as a redirect so the
  // old menu item, bookmarks, and any shared link still land somewhere.
  { path: "/profile", element: <Navigate to="/account/profile" replace /> },
  { path: "/account", element: protectedRoute(<AccountPage />) },
  { path: "/account/:tab", element: protectedRoute(<AccountPage />) },
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
      { path: "map", element: <HuntMapPage /> },
      { path: "compare", element: <ComparePage /> },
      { path: "rubric", element: <RubricPage /> },
      { path: "tasks", element: <TasksPage /> },
      { path: "settings", element: <HuntSettingsPage /> },
      { path: "settings/:tab", element: <HuntSettingsPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
