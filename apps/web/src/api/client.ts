import { ApiError, parseProblem } from "./problem"

let accessToken: string | null = null
let refreshInFlight: Promise<boolean> | null = null

export const setAccessToken = (token: string | null) => {
  accessToken = token
}

export const getAccessToken = () => accessToken

const refreshSession = async (): Promise<boolean> => {
  if (refreshInFlight) {
    return refreshInFlight
  }
  refreshInFlight = (async () => {
    const response = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      credentials: "include",
    })
    if (!response.ok) {
      setAccessToken(null)
      return false
    }
    const body = (await response.json()) as { accessToken: string }
    setAccessToken(body.accessToken)
    return true
  })().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

export const apiFetch = async (path: string, init: RequestInit = {}, retry = true): Promise<Response> => {
  const headers = new Headers(init.headers)
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`)
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "include",
  })
  if (response.status === 401 && retry && !path.includes("/auth/")) {
    const ok = await refreshSession()
    if (ok) {
      return apiFetch(path, init, false)
    }
  }
  return response
}

export const apiJson = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
  const response = await apiFetch(path, init)
  if (response.status === 204) {
    return undefined as T
  }
  if (!response.ok) {
    throw new ApiError(await parseProblem(response))
  }
  if (response.status === 202) {
    return (await response.json()) as T
  }
  const text = await response.text()
  if (!text) {
    return undefined as T
  }
  return JSON.parse(text) as T
}
