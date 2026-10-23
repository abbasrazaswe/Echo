import { afterEach, expect, test, vi } from "vitest";
import { api, allPages, ApiError } from "./api";

afterEach(() => vi.unstubAllGlobals());
test("normalizes validation failures and propagates status for conflict handling", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: [{ msg: "Title required" }] }), {
        status: 422,
      }),
    ),
  );
  await expect(api("/profiles", {})).rejects.toMatchObject({
    status: 422,
    message: "Title required",
  });
});
test("network failure gives actionable backend guidance", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
  );
  await expect(api("/profiles")).rejects.toBeInstanceOf(ApiError);
  await expect(api("/profiles")).rejects.toThrow("port 8001");
});
test("reads all pages without dropping older evidence", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ items: ["first"], total: 2 })),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ items: ["last"], total: 2 })),
    );
  vi.stubGlobal("fetch", fetcher);
  expect(await allPages("/memories?active=true")).toEqual(["first", "last"]);
  expect(fetcher.mock.calls[1][0]).toBe(
    "/memories?active=true&limit=200&offset=200",
  );
});

test("API failures carry a validated request reference for reporting", async () => {
  const reference = "a".repeat(32);
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Try again" }), {
          status: 503,
          headers: { "X-Request-ID": reference },
        }),
      ),
  );
  const { errorText } = await import("./api");
  try {
    await api("/chat", {});
  } catch (error) {
    expect(error).toMatchObject({ requestId: reference, status: 503 });
    expect(errorText(error)).toContain(`Request reference: ${reference}`);
    return;
  }
  throw new Error("Expected failure");
});

test("untrusted or malformed reference headers are not displayed", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response("{}", {
          status: 500,
          headers: { "X-Request-ID": "untrusted-value" },
        }),
      ),
  );
  await expect(api("/chat", {})).rejects.toMatchObject({
    requestId: undefined,
  });
});
