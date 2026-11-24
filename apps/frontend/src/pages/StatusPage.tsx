import type { HealthResponse } from "@mage-med/contracts";
import { useCallback, useEffect, useState } from "react";

import { fetchReadiness } from "../api/health";

type ViewState =
  | { kind: "loading" }
  | { kind: "loaded"; health: HealthResponse }
  | { kind: "failed"; message: string };

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

export function StatusPage() {
  const [state, setState] = useState<ViewState>({ kind: "loading" });

  const loadHealth = useCallback((signal?: AbortSignal) => {
    setState({ kind: "loading" });
    void fetchReadiness(apiBaseUrl, signal)
      .then((health) => setState({ kind: "loaded", health }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError")
          return;
        setState({
          kind: "failed",
          message:
            error instanceof Error
              ? error.message
              : "Backend health check failed",
        });
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadHealth(controller.signal);
    return () => controller.abort();
  }, [loadHealth]);

  return (
    <section aria-labelledby="status-title">
      <div className="max-w-3xl">
        <p className="text-sm font-medium text-cyan-400">
          Milestone 2 · Foundation
        </p>
        <h2
          id="status-title"
          className="mt-2 text-3xl font-semibold tracking-tight"
        >
          System readiness
        </h2>
        <p className="mt-4 text-slate-300">
          This page reports live backend connectivity. It contains no clinical
          records, model output, or simulated metrics.
        </p>
      </div>

      {state.kind === "loading" && (
        <div
          className="mt-8 rounded-xl border border-slate-800 bg-slate-900 p-6"
          role="status"
        >
          Checking the backend…
        </div>
      )}

      {state.kind === "failed" && (
        <div
          className="mt-8 rounded-xl border border-red-900 bg-red-950/40 p-6"
          role="alert"
        >
          <h3 className="font-semibold text-red-300">Backend unavailable</h3>
          <p className="mt-2 text-sm text-red-200">{state.message}</p>
          <button
            className="mt-4 rounded-md bg-red-200 px-3 py-2 text-sm font-semibold text-red-950"
            onClick={() => loadHealth()}
            type="button"
          >
            Retry
          </button>
        </div>
      )}

      {state.kind === "loaded" && (
        <div className="mt-8 rounded-xl border border-slate-800 bg-slate-900 p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h3 className="font-semibold">{state.health.service}</h3>
              <p className="text-sm text-slate-400">
                Version {state.health.version}
              </p>
            </div>
            <span
              className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${
                state.health.status === "healthy"
                  ? "bg-emerald-950 text-emerald-300"
                  : "bg-amber-950 text-amber-300"
              }`}
            >
              {state.health.status === "healthy" ? "Ready" : "Not ready"}
            </span>
          </div>
          <ul className="mt-6 grid gap-3 sm:grid-cols-2">
            {state.health.components.map((component) => (
              <li
                className="rounded-lg border border-slate-800 bg-slate-950 p-4"
                key={component.name}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium capitalize">
                    {component.name}
                  </span>
                  <span
                    className={
                      component.status === "available"
                        ? "text-emerald-400"
                        : "text-amber-400"
                    }
                  >
                    {component.status}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-400">
                  {component.detail}
                </p>
              </li>
            ))}
          </ul>
          <p className="mt-5 font-mono text-xs text-slate-500">
            Request ID: {state.health.request_id}
          </p>
        </div>
      )}
    </section>
  );
}
