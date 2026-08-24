import type { ProblemJson } from "./types"

export class ApiError extends Error {
  readonly problem: ProblemJson

  constructor(problem: ProblemJson) {
    super(problem.title)
    this.name = "ApiError"
    this.problem = problem
  }
}

export const isApiError = (error: unknown): error is ApiError => {
  return error instanceof ApiError
}

export const parseProblem = async (response: Response): Promise<ProblemJson> => {
  try {
    const body = (await response.json()) as ProblemJson
    return {
      type: body.type ?? "about:blank",
      title: body.title ?? response.statusText,
      status: body.status ?? response.status,
      code: body.code ?? "HTTP_ERROR",
      correlationId: body.correlationId ?? "",
      errors: body.errors,
    }
  } catch {
    return {
      type: "about:blank",
      title: response.statusText || "Request failed",
      status: response.status,
      code: "HTTP_ERROR",
      correlationId: "",
    }
  }
}
