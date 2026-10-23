export interface Profile {
  id: string;
  name: string;
}
export interface Session {
  id: string;
  title: string;
  revision: number;
  turn_count: number;
  topic: string | null;
}
export interface Citation {
  message_id?: string;
  memory_id?: string;
  quote: string;
}
export interface Turn {
  id: string;
  role: string;
  content: string;
  citations: Citation[];
  live_citations: Citation[];
  follow_up_question: string | null;
  status: string | null;
}
export interface Memory {
  id: string;
  content: string;
  active: boolean;
  session_id: string;
}
export interface Message {
  id: string;
  speaker: string | null;
  text: string;
  timestamp: string | null;
  source_line_start: number;
  source_line_end: number;
  conversation_id: string;
}
export interface Conversation {
  id: string;
  title: string;
  message_count: number;
}
export interface Page<T> {
  items: T[];
  total: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId?: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  method = "POST",
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: body === undefined ? "GET" : method,
      signal,
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "Cannot reach Echo. Check that the backend is running on port 8001.",
    );
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg: string }) => item.msg).join("; ")
          : `Request failed (${response.status}).`;
    const reference = response.headers.get("X-Request-ID");
    throw new ApiError(
      response.status,
      message,
      reference && /^[a-f0-9]{32}$/.test(reference) ? reference : undefined,
    );
  }
  return data as T;
}

// Read every page so older sessions and memories never silently disappear.
export async function allPages<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T[]> {
  const result: T[] = [];
  for (let offset = 0; ; offset += 200) {
    const page = await api<Page<T>>(
      `${path}${path.includes("?") ? "&" : "?"}limit=200&offset=${offset}`,
      undefined,
      "GET",
      signal,
    );
    result.push(...page.items);
    if (result.length >= page.total || !page.items.length) return result;
  }
}
export async function allSessions(
  path: string,
  signal?: AbortSignal,
): Promise<Session[]> {
  const result: Session[] = [];
  for (let offset = 0; ; offset += 200) {
    const page = await api<Session[]>(
      `${path}?limit=200&offset=${offset}`,
      undefined,
      "GET",
      signal,
    );
    result.push(...page);
    if (page.length < 200) return result;
  }
}

export const errorText = (error: unknown) =>
  error instanceof ApiError && error.requestId
    ? `${error.message} Request reference: ${error.requestId}`
    : error instanceof Error
      ? error.message
      : "Something went wrong. Try again.";
