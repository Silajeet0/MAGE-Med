import { NavLink, Outlet } from "react-router-dom";

export function AppShell() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-slate-950/90">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <div>
            <p className="text-xs font-semibold tracking-[0.24em] text-cyan-400 uppercase">
              Research proof of concept
            </p>
            <h1 className="mt-1 text-xl font-semibold">MAGE-Med</h1>
          </div>
          <nav aria-label="Primary navigation">
            <NavLink
              className="rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 hover:text-white"
              to="/status"
            >
              System status
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-12">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-6xl border-t border-slate-800 px-6 py-6 text-sm text-slate-400">
        Clinician-supervised decision-support research only. No diagnosis,
        prescribing, or treatment.
      </footer>
    </div>
  );
}
