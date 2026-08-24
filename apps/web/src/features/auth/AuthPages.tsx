import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { authApi } from "@/api/resources"
import { setAccessToken } from "@/api/client"
import { useAuth } from "@/app/AuthProvider"
import { ProblemAlert } from "@/components/ProblemAlert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

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
    <div className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>AI Workflow control plane</CardDescription>
        </CardHeader>
        <CardContent>
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
            <Link className="text-xs underline" to="/register">
              Create an account
            </Link>
          </form>
        </CardContent>
      </Card>
    </div>
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
    <div className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Register</CardTitle>
          <CardDescription>Creates a personal workspace</CardDescription>
        </CardHeader>
        <CardContent>
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
            <Link className="text-xs underline" to="/login">
              Already have an account
            </Link>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
