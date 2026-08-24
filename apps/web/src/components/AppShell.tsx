import { NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  Boxes,
  FolderKanban,
  GitBranch,
  KeyRound,
  LogOut,
  PanelLeft,
  PlayCircle,
  ShieldCheck,
  Timer,
  Workflow,
} from "lucide-react"
import { useState } from "react"
import { approvalApi, authApi, projectApi } from "@/api/resources"
import { useAuth } from "@/app/AuthProvider"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const NAV = [
  { to: "projects", label: "Projects", icon: FolderKanban, global: true },
  { to: "workflows", label: "Workflows", icon: Workflow },
  { to: "runs", label: "Runs", icon: PlayCircle },
  { to: "datasets", label: "Datasets", icon: Boxes },
  { to: "credentials", label: "Credentials", icon: KeyRound },
  { to: "triggers", label: "Triggers", icon: Timer },
  { to: "approvals", label: "Approvals", icon: ShieldCheck, global: true },
  { to: "tasks", label: "Tasks", icon: GitBranch },
] as const

export const AppShell = () => {
  const { user, clearSession } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { projectId } = useParams()
  const [expanded, setExpanded] = useState(false)
  const projects = useQuery({ queryKey: ["projects"], queryFn: projectApi.list })
  const approvals = useQuery({ queryKey: ["approvals"], queryFn: () => approvalApi.list() })
  const pendingCount = approvals.data?.filter((item) => item.status === "PENDING").length ?? 0

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } catch {
      /* still clear */
    }
    clearSession()
    navigate("/login")
  }

  const handleProjectChange = (next: string) => {
    const rest = location.pathname.split("/").slice(3).join("/") || "workflows"
    navigate(`/projects/${next}/${rest.startsWith("projects") ? "workflows" : rest}`)
  }

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-background focus:p-2">
        Skip to main
      </a>
      <aside
        className={cn(
          "flex flex-col border-r bg-sidebar text-sidebar-foreground",
          expanded ? "w-[200px]" : "w-14",
        )}
      >
        <div className="flex h-12 items-center justify-center border-b">
          <Button
            variant="ghost"
            size="icon"
            aria-label={expanded ? "Collapse navigation" : "Expand navigation"}
            onClick={() => setExpanded((value) => !value)}
          >
            <PanelLeft />
          </Button>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-2" aria-label="Main">
          {NAV.map((item) => {
            const Icon = item.icon
            const href =
              item.to === "projects"
                ? "/projects"
                : item.to === "approvals"
                  ? "/approvals"
                  : projectId
                    ? `/projects/${projectId}/${item.to}`
                    : "/projects"
            return (
              <Tooltip key={item.to}>
                <TooltipTrigger asChild>
                  <NavLink
                    to={href}
                    aria-label={item.label}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 rounded-md px-2 py-2 text-sm hover:bg-sidebar-accent",
                        isActive && "bg-sidebar-accent font-medium",
                      )
                    }
                  >
                    <Icon className="size-4 shrink-0" />
                    {expanded ? <span>{item.label}</span> : null}
                    {item.to === "approvals" && pendingCount > 0 ? (
                      <span className="ml-auto rounded bg-primary px-1 text-[10px] text-primary-foreground">
                        {pendingCount}
                      </span>
                    ) : null}
                  </NavLink>
                </TooltipTrigger>
                {!expanded ? <TooltipContent side="right">{item.label}</TooltipContent> : null}
              </Tooltip>
            )
          })}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between border-b px-4">
          <div className="flex min-w-0 items-center gap-3">
            <Select value={projectId} onValueChange={handleProjectChange}>
              <SelectTrigger className="w-56" aria-label="Select project">
                <SelectValue placeholder="Select a project" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {projects.data?.items.map((project) => (
                    <SelectItem key={project.projectId} value={project.projectId}>
                      {project.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" aria-label="User menu">
                {user?.email}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuGroup>
                <DropdownMenuLabel>{user?.displayName}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => void handleLogout()}>
                  <LogOut />
                  Log out
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <main id="main" className="min-h-0 flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
