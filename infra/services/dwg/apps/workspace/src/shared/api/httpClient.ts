type RuntimeValidator<T> = (value: unknown) => value is T;

export async function getJson<T>(
  url: string,
  signal: AbortSignal | undefined,
  validate: RuntimeValidator<T>
): Promise<T> {
  const response = await fetch(url, { signal });
  return readJson(response, validate);
}

export async function postJson<T>(
  url: string,
  body: unknown,
  signal: AbortSignal | undefined,
  validate: RuntimeValidator<T>
): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal
  });
  return readJson(response, validate);
}

async function readJson<T>(
  response: Response,
  validate: RuntimeValidator<T>
): Promise<T> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`Invalid JSON response (HTTP ${response.status})`);
  }
  if (!response.ok) {
    const errorValue = typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>).error
      : undefined;
    const error = typeof errorValue === "string"
      ? errorValue
      : errorValue && typeof errorValue === "object" &&
          typeof (errorValue as Record<string, unknown>).message === "string"
        ? (errorValue as { message: string }).message
        : `HTTP ${response.status}`;
    throw new Error(error);
  }
  if (!validate(payload)) throw new Error("Response contract validation failed");
  return payload;
}
