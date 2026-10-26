import { afterEach, expect, test, vi } from "vitest";
import { getApiKey, streamUrl } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

test("stream URLs carry a run-bound token, never the API key", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ token: "tok.sig", expires_in: 60 }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);

  const url = new URL(await streamUrl("run_1", 7));

  expect(url.pathname).toBe("/api/v1/runs/run_1/stream");
  expect(url.searchParams.get("token")).toBe("tok.sig");
  expect(url.searchParams.get("after")).toBe("7");
  expect(url.toString()).not.toContain(getApiKey());
  const [tokenUrl, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
  expect(String(tokenUrl)).toContain("/api/v1/runs/run_1/stream-token");
  expect((init.headers as Record<string, string>)["X-API-Key"]).toBe(getApiKey());
});
