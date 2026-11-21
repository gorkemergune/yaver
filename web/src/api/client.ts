export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function withJson(init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  return { ...init, headers };
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

/** GET JSON from the backend. All paths are relative to `/api`. */
export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return parse<T>(await fetch(`/api${path}`, withJson(init)));
}

/** POST JSON to the backend. */
export async function apiPost<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const options = withJson({ ...init, method: "POST" });
  const headers = new Headers(options.headers);
  if (body !== undefined) headers.set("Content-Type", "application/json");
  return parse<T>(
    await fetch(`/api${path}`, {
      ...options,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );
}

/** DELETE on the backend (JSON answer). */
export async function apiDelete<T>(path: string, init?: RequestInit): Promise<T> {
  return parse<T>(await fetch(`/api${path}`, withJson({ ...init, method: "DELETE" })));
}
