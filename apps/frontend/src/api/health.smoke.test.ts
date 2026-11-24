import { describe, expect, it } from "vitest";

import { fetchReadiness } from "./health";

describe("live frontend-to-backend-to-Neo4j smoke", () => {
  it("receives real ready status through the frontend API client", async () => {
    const backendUrl =
      process.env.MAGE_MED_BACKEND_URL ?? "http://127.0.0.1:8000";
    const response = await fetchReadiness(backendUrl);

    expect(response.status, JSON.stringify(response)).toBe("healthy");
    expect(response.components, JSON.stringify(response)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: "sqlite", status: "available" }),
        expect.objectContaining({ name: "neo4j", status: "available" }),
      ]),
    );
    expect(response.request_id).not.toHaveLength(0);
  });
});
