import { Navigate, Outlet, createBrowserRouter } from "react-router-dom"
import { useAuth } from "./AuthProvider"
import { AppShell } from "@/components/AppShell"
import { LoginPage, RegisterPage } from "@/features/auth/AuthPages"
import { ProjectsPage } from "@/features/projects/ProjectsPage"
import { WorkflowsPage } from "@/features/workflows/WorkflowsPage"
import { WorkflowBuilder } from "@/features/builder/WorkflowBuilder"
import { RunsPage } from "@/features/runs/RunsPage"
import { RunDetailPage } from "@/features/runs/RunDetailPage"
import { DatasetsPage } from "@/features/datasets/DatasetsPage"
import { CredentialsPage } from "@/features/credentials/CredentialsPage"
import { TriggersPage } from "@/features/triggers/TriggersPage"
import { ApprovalsPage } from "@/features/approvals/ApprovalsPage"
import { TaskDetailPage, TasksPage } from "@/features/tasks/TasksPage"

const RequireAuth = () => {
  const { user, ready } = useAuth()
  if (!ready) {
    return <p className="p-6 text-sm text-muted-foreground">Loading session…</p>
  }
  if (!user) {
    return <Navigate to="/login" replace />
  }
  return <Outlet />
}

const PublicOnly = () => {
  const { user, ready } = useAuth()
  if (!ready) {
    return <p className="p-6 text-sm text-muted-foreground">Loading session…</p>
  }
  if (user) {
    return <Navigate to="/projects" replace />
  }
  return <Outlet />
}

export const router = createBrowserRouter([
  {
    element: <PublicOnly />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <RegisterPage /> },
    ],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: "/projects", element: <ProjectsPage /> },
          { path: "/approvals", element: <ApprovalsPage /> },
          { path: "/projects/:projectId/workflows", element: <WorkflowsPage /> },
          { path: "/projects/:projectId/workflows/:workflowId", element: <WorkflowBuilder /> },
          { path: "/projects/:projectId/runs", element: <RunsPage /> },
          { path: "/projects/:projectId/runs/:runId", element: <RunDetailPage /> },
          { path: "/projects/:projectId/datasets", element: <DatasetsPage /> },
          { path: "/projects/:projectId/credentials", element: <CredentialsPage /> },
          { path: "/projects/:projectId/triggers", element: <TriggersPage /> },
          { path: "/projects/:projectId/tasks", element: <TasksPage /> },
          { path: "/projects/:projectId/tasks/:taskId", element: <TaskDetailPage /> },
        ],
      },
    ],
  },
  { path: "/", element: <Navigate to="/projects" replace /> },
  { path: "*", element: <Navigate to="/projects" replace /> },
])
