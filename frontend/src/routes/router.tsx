// Route table (Phase 1 plan §5.2, DESIGN §13.1 subset). NOT /compare or
// /invite/:token — those are Phase 2/3.
import { createBrowserRouter, Navigate } from "react-router-dom";

import { LoginPage } from "../auth/LoginPage";
import { RequireAuth } from "../auth/RequireAuth";
import { AppLayout } from "../components/AppLayout";
import { HuntSwitcherPage } from "../features/hunts/HuntSwitcherPage";
import { HuntSettingsPage } from "../features/hunts/HuntSettingsPage";
import { OverviewPage } from "../features/listings/OverviewPage";
import { TasksActivePage } from "../features/jobs/TasksActivePage";
import { RubricWizardPage } from "../features/rubric/RubricWizardPage";

const protectedRoute = (element: React.ReactNode) => <RequireAuth>{element}</RequireAuth>;

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: protectedRoute(<HuntSwitcherPage />),
  },
  {
    path: "/h/:huntId",
    element: protectedRoute(<AppLayout />),
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "rubric", element: <RubricWizardPage /> },
      { path: "tasks", element: <TasksActivePage /> },
      { path: "settings", element: <HuntSettingsPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
