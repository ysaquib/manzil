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
import { AdminFeedbackPage } from "../features/admin/AdminFeedbackPage";
import { AdminDemoPage } from "../features/admin/AdminDemoPage";
import { AdminAuditPage } from "../features/admin/AdminAuditPage";
import { AdminCostsPage } from "../features/admin/AdminCostsPage";
import { AdminHuntsPage } from "../features/admin/AdminHuntsPage";
import { AdminJobsPage } from "../features/admin/AdminJobsPage";
import { AdminSystemPage } from "../features/admin/AdminSystemPage";
import { AdminLayout } from "../features/admin/AdminLayout";
import { AdminOverviewPage } from "../features/admin/AdminOverviewPage";
import { AdminPeoplePage } from "../features/admin/AdminPeoplePage";
import { HuntSwitcherPage } from "../features/hunts/HuntSwitcherPage";
import { HuntSettingsPage } from "../features/hunts/HuntSettingsPage";
import { InviteAcceptPage } from "../features/invites/InviteAcceptPage";
import { InvitationLinkJoinPage } from "../features/invites/InvitationLinkJoinPage";
import { ComparePage } from "../features/listings/ComparePage";
import { OverviewPage } from "../features/listings/OverviewPage";
import { HuntMapPage } from "../features/map/HuntMapPage";
import { TasksPage } from "../features/jobs/TasksPage";
import { RubricPage } from "../features/rubric/RubricPage";
import { VisitCreatePage } from "../features/visits/VisitCreatePage";
import { VisitDetailPage } from "../features/visits/VisitDetailPage";
import { VisitsPage } from "../features/visits/VisitsPage";

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
  // Outside the /h/:huntId tree on purpose: nothing in the panel is Hunt-scoped,
  // and it has its own shell rather than the hunt navbar (AD-2).
  {
    path: "/admin",
    element: protectedRoute(<AdminLayout />),
    children: [
      { index: true, element: <AdminOverviewPage /> },
      { path: "people", element: <AdminPeoplePage /> },
      { path: "hunts", element: <AdminHuntsPage /> },
      { path: "jobs", element: <AdminJobsPage /> },
      { path: "costs", element: <AdminCostsPage /> },
      { path: "system", element: <AdminSystemPage /> },
      { path: "audit", element: <AdminAuditPage /> },
      { path: "feedback", element: <AdminFeedbackPage /> },
      { path: "demo", element: <AdminDemoPage /> },
    ],
  },
  {
    path: "/h/:huntId",
    element: protectedRoute(<AppLayout />),
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "map", element: <HuntMapPage /> },
      { path: "compare", element: <ComparePage /> },
      // `visits/new` before `visits/:visitId` so the literal wins the match.
      { path: "visits", element: <VisitsPage /> },
      { path: "visits/new", element: <VisitCreatePage /> },
      { path: "visits/:visitId", element: <VisitDetailPage /> },
      { path: "rubric", element: <RubricPage /> },
      { path: "tasks", element: <TasksPage /> },
      { path: "settings", element: <HuntSettingsPage /> },
      { path: "settings/:tab", element: <HuntSettingsPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
