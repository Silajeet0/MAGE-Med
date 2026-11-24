import type {
  ComponentCheck,
  ComponentStatus,
  HealthResponse,
  HealthStatus,
} from "@mage-med/contracts";

const healthStatuses: ReadonlySet<HealthStatus> = new Set([
  "healthy",
  "not_ready",
]);
const componentStatuses: ReadonlySet<ComponentStatus> = new Set([
  "available",
  "unavailable",
]);

function isComponentCheck(value: unknown): value is ComponentCheck {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.name === "string" &&
    typeof candidate.detail === "string" &&
    typeof candidate.status === "string" &&
    componentStatuses.has(candidate.status as ComponentStatus)
  );
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.service === "string" &&
    typeof candidate.version === "string" &&
    typeof candidate.request_id === "string" &&
    typeof candidate.status === "string" &&
    healthStatuses.has(candidate.status as HealthStatus) &&
    Array.isArray(candidate.components) &&
    candidate.components.every(isComponentCheck)
  );
}

export async function fetchReadiness(
  apiBaseUrl: string,
  signal?: AbortSignal,
  fetchImplementation: typeof fetch = fetch,
): Promise<HealthResponse> {
  const request: RequestInit = { headers: { Accept: "application/json" } };
  if (signal !== undefined) request.signal = signal;
  const response = await fetchImplementation(
    `${apiBaseUrl}/api/v1/health/ready`,
    request,
  );
  const payload: unknown = await response.json();
  if (!isHealthResponse(payload)) {
    throw new Error("Backend returned an invalid health response");
  }
  return payload;
}
