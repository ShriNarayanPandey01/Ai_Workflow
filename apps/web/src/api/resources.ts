import { apiFetch, apiJson, setAccessToken } from "./client"
import type {
  Approval,
  ArtifactDownload,
  Credential,
  CursorPage,
  Dataset,
  DocumentRecord,
  DraftResponse,
  ExecutionDetail,
  ExecutionSummary,
  NodeManifest,
  Project,
  TaskDetail,
  TaskItemView,
  TaskSummary,
  TokenResponse,
  Trigger,
  UploadIntent,
  User,
  ValidateResponse,
  VersionDetail,
  VersionSummary,
  WorkflowDefinition,
  WorkflowSummary,
} from "./types"

export const authApi = {
  register: (email: string, password: string, displayName: string) =>
    apiJson<TokenResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, displayName }),
    }),
  login: (email: string, password: string) =>
    apiJson<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  refresh: () => apiJson<TokenResponse>("/api/v1/auth/refresh", { method: "POST" }),
  logout: async () => {
    await apiJson<void>("/api/v1/auth/logout", { method: "POST" })
    setAccessToken(null)
  },
  me: () => apiJson<{ user: User }>("/api/v1/auth/me"),
}

export const projectApi = {
  list: () => apiJson<CursorPage<Project>>("/api/v1/projects?limit=100"),
  create: (name: string, description?: string) =>
    apiJson<Project>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  get: (projectId: string) => apiJson<Project>(`/api/v1/projects/${projectId}`),
}

export const catalogApi = {
  list: () => apiJson<{ items: NodeManifest[] }>("/api/v1/node-catalog"),
}

export const workflowApi = {
  list: (projectId: string) =>
    apiJson<CursorPage<WorkflowSummary>>(`/api/v1/projects/${projectId}/workflows?limit=100`),
  create: (projectId: string, name: string, description?: string) =>
    apiJson<WorkflowSummary>(`/api/v1/projects/${projectId}/workflows`, {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  get: (projectId: string, workflowId: string) =>
    apiJson<WorkflowSummary>(`/api/v1/projects/${projectId}/workflows/${workflowId}`),
  getDraft: (projectId: string, workflowId: string) =>
    apiJson<DraftResponse>(`/api/v1/projects/${projectId}/workflows/${workflowId}/draft`),
  putDraft: (projectId: string, workflowId: string, baseRevision: number, definition: WorkflowDefinition) =>
    apiJson<DraftResponse>(`/api/v1/projects/${projectId}/workflows/${workflowId}/draft`, {
      method: "PUT",
      body: JSON.stringify({ baseRevision, definition }),
    }),
  validate: (projectId: string, workflowId: string) =>
    apiJson<ValidateResponse>(`/api/v1/projects/${projectId}/workflows/${workflowId}/validate`, {
      method: "POST",
    }),
  publish: (projectId: string, workflowId: string) =>
    apiJson<VersionDetail>(`/api/v1/projects/${projectId}/workflows/${workflowId}/publish`, {
      method: "POST",
    }),
  versions: (projectId: string, workflowId: string) =>
    apiJson<VersionSummary[]>(`/api/v1/projects/${projectId}/workflows/${workflowId}/versions`),
}

export const executionApi = {
  start: (
    projectId: string,
    workflowId: string,
    body: { mode: string; input: unknown; idempotencyKey: string; workflowVersionId?: string },
  ) =>
    apiJson<{ runId: string }>(`/api/v1/projects/${projectId}/workflows/${workflowId}/executions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  list: (projectId: string) =>
    apiJson<CursorPage<ExecutionSummary>>(`/api/v1/projects/${projectId}/executions?limit=50`),
  get: (projectId: string, runId: string) =>
    apiJson<ExecutionDetail>(`/api/v1/projects/${projectId}/executions/${runId}`),
  cancel: (projectId: string, runId: string) =>
    apiJson<ExecutionSummary>(`/api/v1/projects/${projectId}/executions/${runId}/cancel`, {
      method: "POST",
    }),
  events: (projectId: string, runId: string, lastEventId?: string) => {
    const headers: HeadersInit = {}
    if (lastEventId) {
      headers["Last-Event-ID"] = lastEventId
    }
    return apiFetch(`/api/v1/projects/${projectId}/executions/${runId}/events`, { headers })
  },
}

export const credentialApi = {
  list: (projectId: string) => apiJson<Credential[]>(`/api/v1/projects/${projectId}/credentials`),
  create: (projectId: string, type: string, name: string, data: unknown) =>
    apiJson<Credential>(`/api/v1/projects/${projectId}/credentials`, {
      method: "POST",
      body: JSON.stringify({ type, name, data }),
    }),
  update: (projectId: string, credentialId: string, name?: string, data?: unknown) =>
    apiJson<Credential>(`/api/v1/projects/${projectId}/credentials/${credentialId}`, {
      method: "PUT",
      body: JSON.stringify({ name, data }),
    }),
  delete: (projectId: string, credentialId: string) =>
    apiJson<void>(`/api/v1/projects/${projectId}/credentials/${credentialId}`, { method: "DELETE" }),
}

export const datasetApi = {
  list: (projectId: string) => apiJson<Dataset[]>(`/api/v1/projects/${projectId}/datasets`),
  create: (projectId: string, name: string) =>
    apiJson<Dataset>(`/api/v1/projects/${projectId}/datasets`, {
      method: "POST",
      body: JSON.stringify({ name, embeddingConfig: { model: "text-embedding-3-small" } }),
    }),
  uploadIntent: (projectId: string, datasetId: string, originalName: string, mediaType: string, sizeBytes: number) =>
    apiJson<UploadIntent>(`/api/v1/projects/${projectId}/datasets/${datasetId}/documents/uploads`, {
      method: "POST",
      body: JSON.stringify({ originalName, mediaType, sizeBytes }),
    }),
  confirm: (projectId: string, datasetId: string, documentId: string, contentHash: string) =>
    apiJson<DocumentRecord>(`/api/v1/projects/${projectId}/datasets/${datasetId}/documents`, {
      method: "POST",
      body: JSON.stringify({ documentId, contentHash }),
    }),
  documents: (projectId: string, datasetId: string) =>
    apiJson<DocumentRecord[]>(`/api/v1/projects/${projectId}/datasets/${datasetId}/documents`),
  deleteDocument: (projectId: string, datasetId: string, documentId: string) =>
    apiJson<void>(`/api/v1/projects/${projectId}/datasets/${datasetId}/documents/${documentId}`, {
      method: "DELETE",
    }),
}

export const triggerApi = {
  list: (projectId: string, workflowId: string) =>
    apiJson<Trigger[]>(`/api/v1/projects/${projectId}/workflows/${workflowId}/triggers`),
  create: (
    projectId: string,
    workflowId: string,
    body: { type: string; name: string; workflowVersionId: string; config?: unknown },
  ) =>
    apiJson<Trigger>(`/api/v1/projects/${projectId}/workflows/${workflowId}/triggers`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patch: (
    projectId: string,
    workflowId: string,
    triggerId: string,
    body: { status?: string; workflowVersionId?: string; config?: unknown },
  ) =>
    apiJson<Trigger>(`/api/v1/projects/${projectId}/workflows/${workflowId}/triggers/${triggerId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  delete: (projectId: string, workflowId: string, triggerId: string) =>
    apiJson<void>(`/api/v1/projects/${projectId}/workflows/${workflowId}/triggers/${triggerId}`, {
      method: "DELETE",
    }),
}

export const approvalApi = {
  list: (projectId?: string) =>
    apiJson<Approval[]>(projectId ? `/api/v1/approvals?projectId=${projectId}` : "/api/v1/approvals"),
  decide: (projectId: string, runId: string, approvalId: string, decision: string, payload?: unknown) =>
    apiJson<Approval>(
      `/api/v1/projects/${projectId}/executions/${runId}/approvals/${approvalId}/decision`,
      { method: "POST", body: JSON.stringify({ decision, payload }) },
    ),
}

export const taskApi = {
  listForRun: (projectId: string, runId: string) =>
    apiJson<TaskSummary[]>(`/api/v1/projects/${projectId}/executions/${runId}/tasks`),
  get: (projectId: string, taskId: string) =>
    apiJson<TaskDetail>(`/api/v1/projects/${projectId}/tasks/${taskId}`),
  items: (projectId: string, taskId: string) =>
    apiJson<CursorPage<TaskItemView>>(`/api/v1/projects/${projectId}/tasks/${taskId}/items?limit=50`),
  cancel: (projectId: string, taskId: string) =>
    apiJson<{ taskId: string; status: string }>(`/api/v1/projects/${projectId}/tasks/${taskId}/cancel`, {
      method: "POST",
    }),
  download: (projectId: string, artifactId: string) =>
    apiJson<ArtifactDownload>(`/api/v1/projects/${projectId}/artifacts/${artifactId}/download`),
}
