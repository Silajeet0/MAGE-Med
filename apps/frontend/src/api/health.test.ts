import { describe, expect, it, vi } from "vitest";

import { fetchReadiness } from "./health";

describe("fetchReadiness", () => {
  it("accepts a typed healthy backend response", async () => {
    const fetchImplementation = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          service: "mage-med-backend",
          version: "0.1.0",
          status: "healthy",
          request_id: "unit-test",
          components: [
            {
              name: "sqlite",
              status: "available",
              detail: "connectivity verified",
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const response = await fetchReadiness(
      "http://backend.test",
      undefined,
      fetchImplementation,
    );

    expect(response.status).toBe("healthy");
    expect(fetchImplementation).toHaveBeenCalledWith(
      "http://backend.test/api/v1/health/ready",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("rejects malformed payloads instead of inventing a status", async () => {
    const fetchImplementation = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: "healthy" }), { status: 200 }),
      );

    await expect(
      fetchReadiness("http://backend.test", undefined, fetchImplementation),
    ).rejects.toThrow("invalid health response");
  });
});
