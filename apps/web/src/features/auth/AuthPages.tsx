import { useState, type ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { authApi } from "@/api/resources"
import { setAccessToken } from "@/api/client"
import { useAuth } from "@/app/AuthProvider"
import { ProblemAlert } from "@/components/ProblemAlert"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

const Wordmark = ({ className }: { className?: string }) => (
  <span className={className}>
    <span className="flex items-center gap-2">
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
        <rect x="1.5" y="1.5" width="15" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="5.5" cy="6.5" r="1.4" fill="var(--primary)" />
        <circle cx="5.5" cy="11.5" r="1.4" fill="var(--node-human)" />
        <path d="M8 6.5h4M8 11.5h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <span className="font-display text-[15px] font-bold tracking-tight [font-stretch:112%]">ai-workflow</span>
    </span>
  </span>
)

const GraphMotif = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 380 120"
    role="img"
    aria-label="Workflow graph: input feeding an AI model through a condition into a human approval gate, then output"
    fill="none"
  >
    <path d="M26 60H86" stroke="var(--border)" strokeWidth="1.5" />
    <path d="M106 60H176" stroke="var(--border)" strokeWidth="1.5" />
    <path d="M196 56C226 52 236 32 264 30" stroke="var(--border)" strokeWidth="1.5" />
    <path d="M288 26C320 24 340 46 344 74" stroke="var(--border)" strokeWidth="1.5" />
    <path d="M196 64C240 72 304 84 336 88" stroke="var(--border)" strokeWidth="1.5" strokeDasharray="3 4" />
    <circle cx="16" cy="60" r="6" fill="var(--node-data)" />
    <circle cx="96" cy="60" r="6" fill="var(--node-ai)" />
    <circle cx="186" cy="60" r="6" fill="var(--node-control)" />
    <circle className="motion-safe:animate-pulse" cx="276" cy="28" r="11" fill="var(--human-gold)" opacity="0.25" />
    <circle cx="276" cy="28" r="6" fill="var(--node-human)" />
    <circle cx="346" cy="88" r="6" fill="var(--node-data)" />
    <g fontFamily="var(--font-mono)" fontSize="8" fill="var(--muted-foreground)">
      <text x="16" y="80" textAnchor="middle">input</text>
      <text x="96" y="80" textAnchor="middle">ai.chat</text>
      <text x="186" y="80" textAnchor="middle">condition</text>
      <text x="276" y="12" textAnchor="middle">approval</text>
      <text x="346" y="108" textAnchor="middle">output</text>
    </g>
  </svg>
)

const BrandPanel = () => (
  <aside className="canvas-dots relative hidden flex-col justify-between gap-10 border-r p-10 lg:flex">
    <Wordmark />
    <div className="max-w-lg space-y-10">
      <GraphMotif className="w-full" />
      <div className="space-y-3">
        <h2 className="font-display text-4xl leading-[1.05] font-black tracking-tight [font-stretch:118%]">
          Build the graph.
          <br />
          Trust the run.
        </h2>
        <p className="max-w-md text-sm leading-relaxed text-muted-foreground">
          Durable workflow runs with humans wired in. Every step is checkpointed,
          validated twice, and streamed back live.
        </p>
      </div>
    </div>
    <p className="font-mono text-xs text-muted-foreground">execution.trace · awaiting operator</p>
  </aside>
)

const AuthLayout = ({ children }: { children: ReactNode }) => (
  <div className="grid min-h-screen lg:grid-cols-[1fr_440px]">
    <BrandPanel />
    <main className="flex flex-col justify-center px-6 py-12 sm:px-10">
      <div className="mx-auto w-full max-w-sm">
        <div className="mb-10 lg:hidden">
          <Wordmark />
        </div>
        {children}
      </div>
    </main>
  </div>
)

export const LoginPage = () => {
  const { setSession } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const mutation = useMutation({
    mutationFn: () => authApi.login(email, password),
    onSuccess: (tokens) => {
      setAccessToken(tokens.accessToken)
      setSession(tokens.accessToken, tokens.user)
      navigate("/projects")
    },
  })

  return (
    <AuthLayout>
      <div className="space-y-6">
        <div className="space-y-1">
          <h1 className="font-display text-xl font-bold tracking-tight [font-stretch:110%]">Sign in</h1>
          <p className="text-sm text-muted-foreground">To your AI Workflow workspace</p>
        </div>
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            mutation.mutate()
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <ProblemAlert error={mutation.error} />
          <Button type="submit" disabled={mutation.isPending}>
            Sign in
          </Button>
          <Link className="text-xs underline underline-offset-2 hover:text-primary" to="/register">
            Create an account
          </Link>
        </form>
      </div>
    </AuthLayout>
  )
}

export const RegisterPage = () => {
  const { setSession } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [displayName, setDisplayName] = useState("")
  const mutation = useMutation({
    mutationFn: () => authApi.register(email, password, displayName),
    onSuccess: (tokens) => {
      setAccessToken(tokens.accessToken)
      setSession(tokens.accessToken, tokens.user)
      navigate("/projects")
    },
  })

  return (
    <AuthLayout>
      <div className="space-y-6">
        <div className="space-y-1">
          <h1 className="font-display text-xl font-bold tracking-tight [font-stretch:110%]">Create your account</h1>
          <p className="text-sm text-muted-foreground">This starts a personal workspace</p>
        </div>
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            mutation.mutate()
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="name">Display name</Label>
            <Input id="name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <ProblemAlert error={mutation.error} />
          <Button type="submit" disabled={mutation.isPending}>
            Create account
          </Button>
          <Link className="text-xs underline underline-offset-2 hover:text-primary" to="/login">
            Already have an account
          </Link>
        </form>
      </div>
    </AuthLayout>
  )
}
