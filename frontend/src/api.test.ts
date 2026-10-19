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
