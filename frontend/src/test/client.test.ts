import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "../api/client";

describe("ApiClient", () => {
  afterEach(() => vi.restoreAllMocks());
  it("sends the bearer token and serialized incident filters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    await new ApiClient("operator-token", undefined, "/api").get("/v1/incidents", { status: "open", limit: 10 });
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("status=open");
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toEqual({ Authorization: "Bearer operator-token" });
  });
  it("clears the session through the unauthorized callback", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 401 }));
    const expired = vi.fn();
    await expect(new ApiClient("operator-token", expired, "/api").get("/v1/incidents")).rejects.toMatchObject({ code: "unauthorized" } satisfies Partial<ApiError>);
    expect(expired).toHaveBeenCalledOnce();
  });
  it("preserves session behavior for forbidden responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 403 }));
    const expired = vi.fn();
    await expect(new ApiClient("operator-token", expired, "/api").get("/v1/incidents")).rejects.toMatchObject({ message: "Insufficient permissions", code: "forbidden" });
    expect(expired).not.toHaveBeenCalled();
  });
});
