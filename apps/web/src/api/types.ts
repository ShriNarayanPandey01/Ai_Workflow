export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue }

export type CursorPage<T> = {
  items: T[]
  nextCursor: string | null
}

export type ProblemError = {
  code: string
  path?: string | null
  nodeId?: string | null
  edgeId?: string | null
  message: string
}

export type ProblemJson = {
  type: string
  title: string
  status: number
  code: string
  correlationId: string
  detail?: string
  errors?: ProblemError[] | null
}

export type User = {
  userId: string
  email: string
  displayName: string
  workspaceId: string
  workspaceKind: string
}

export type TokenResponse = {
  accessToken: string
  tokenType: string
  expiresIn: number
  user: User
}

export type Project = {
  projectId: string
  workspaceId: string
  name: string
  description?: string | null
  createdAt: string
  updatedAt: string
}

export type WorkflowSummary = {
  workflowId: string
  projectId: string
  name: string
  description?: string | null
  latestVersion: number
  createdAt: string
  updatedAt: string
}

export type DraftResponse = {
  workflowId: string
  revision: number
  definition: WorkflowDefinition
  updatedAt: string
}

export type ValidateResponse = {
  valid: boolean
  errors: ProblemError[]
}

export type VersionSummary = {
  versionId: string
  versionNumber: number
  definitionHash: string
  publishedAt: string
}

export type VersionDetail = VersionSummary & {
  workflowId: string
  definition: WorkflowDefinition
}

export type Position = { x: number; y: number }

export type InputBinding = {
  target_port: string
  target_path: string
  source_node_id: string
  source_port: string
  source_path: string
  origin: "user" | "default" | "pass_through"
}

export type Operand =
  | { kind: "path"; value: string }
  | { kind: "literal"; value: JsonValue }

export type ConditionExpression =
  | { op: "all" | "any"; args: ConditionExpression[] }
  | { op: "not"; arg: ConditionExpression }
  | {
      op: "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "contains" | "startsWith" | "endsWith"
      left: Operand
      right: Operand
    }
  | { op: "exists" | "isNull"; value: Operand }

export type WorkflowEdge = {
  id: string
  source_node_id: string
  source_port: string
  target_node_id: string
  target_port: string
  label?: string | null
  condition?: ConditionExpression | null
}

export type WorkflowNode = {
  id: string
  type: string
  position: Position
  config: Record<string, JsonValue>
  credential_refs?: Record<string, string>
  resource_refs?: Record<string, string>
  input_bindings?: InputBinding[]
}

export type RetryPolicy = {
  max_attempts: number
  initial_backoff_ms: number
  max_backoff_ms: number
  multiplier: number
  jitter: boolean
}

export type ExecutionPolicy = {
  timeout_seconds: number
  max_node_executions: number
  max_parallel_nodes: number
  max_fan_out_items: number
  max_task_seconds: number
  max_provider_calls: number
  max_artifact_bytes: number
  max_estimated_cost?: number | null
  default_retry: RetryPolicy
}

export type WorkflowDefinition = {
  schema_version: "1.0"
  workflow_id: string
  workflow_version_id?: string
  name: string
  input_schema: Record<string, JsonValue>
  output_schema: Record<string, JsonValue>
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  execution_policy: ExecutionPolicy
}

export type PortDefinition = {
  name: string
  direction: "input" | "output"
  required: boolean
  cardinality: "single" | "optional" | "multiple"
  schema: Record<string, JsonValue>
  description?: string
  default_bindings?: Array<{
    target_path: string
    match: { source_ports: string[]; source_paths: string[] }
  }>
}

export type NodeManifest = {
  type: string
  display_name: string
  description: string
  category: string
  execution_owner: string
  inputs: PortDefinition[]
  outputs: PortDefinition[]
  config_schema: Record<string, JsonValue>
  credential_slots: Array<{
    name: string
    credential_type: string
    required: boolean
    description?: string
  }>
  resource_slots: Array<{
    name: string
    resource_type: string
    required: boolean
  }>
  capabilities?: Record<string, JsonValue>
  ui: { icon: string; color_token: string; inspector?: string | null }
}

export type RunStatus =
  | "QUEUED"
  | "RUNNING"
  | "WAITING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLING"
  | "CANCELLED"
  | "TIMED_OUT"

export type ExecutionSummary = {
  runId: string
  workflowId: string
  workflowVersionId?: string | null
  mode: string
  status: RunStatus
  waitingReason?: string | null
  createdAt: string
  updatedAt: string
}

export type NodeExecutionView = {
  nodeId: string
  attempt: number
  status: string
  input?: JsonValue
  output?: JsonValue
  error?: JsonValue
}

export type ExecutionDetail = ExecutionSummary & {
  projectId: string
  interruptId?: string | null
  input?: JsonValue
  output?: JsonValue
  lastSequence: number
  errorCode?: string | null
  nodes: NodeExecutionView[]
}

export type Credential = {
  credentialId: string
  projectId: string
  type: string
  name: string
  maskedHint?: string | null
  keyId: string
  createdAt: string
  updatedAt: string
}

export type Dataset = {
  datasetId: string
  projectId: string
  name: string
  embeddingConfig?: JsonValue
  createdAt: string
  updatedAt: string
}

export type DocumentRecord = {
  documentId: string
  datasetId: string
  originalName: string
  mediaType: string
  sizeBytes: number
  contentHash?: string | null
  version: number
  status: string
  errorCode?: string | null
  chunkCount?: number | null
  createdAt: string
  updatedAt: string
}

export type UploadIntent = {
  documentId: string
  objectKey: string
  uploadUrl: string
  headers: Record<string, string>
  expiresAt: string
}

export type Trigger = {
  triggerId: string
  workflowId: string
  workflowVersionId: string
  type: string
  name: string
  status: string
  config?: JsonValue
  publicId?: string | null
  secret?: string | null
  createdAt: string
  updatedAt: string
}

export type Approval = {
  approvalId: string
  runId: string
  projectId: string
  nodeId: string
  interruptId: string
  status: string
  request?: JsonValue
  decision?: JsonValue
  createdAt: string
}

export type TaskSummary = {
  taskId: string
  runId: string
  nodeId: string
  taskType: string
  status: string
  stage?: string | null
  totalItems: number
  completedItems: number
  failedItems: number
  skippedItems: number
  percent: number
  createdAt: string
  updatedAt: string
}

export type TaskDetail = TaskSummary & {
  waitingReason?: string | null
  usage?: JsonValue
  warnings?: JsonValue
}

export type TaskItemView = {
  itemId: string
  itemKey: string
  status: string
  attempt: number
  result?: JsonValue
  error?: JsonValue
  createdAt: string
}

export type ArtifactDownload = {
  artifactId: string
  objectKey: string
  downloadUrl: string
  expiresAt: string
}

export type SseConnectionState = "connected" | "reconnecting" | "offline" | "ended"
