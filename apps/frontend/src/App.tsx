import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { StatusPage } from "./pages/StatusPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<StatusPage />} />
        <Route path="status" element={<StatusPage />} />
        <Route path="*" element={<Navigate replace to="/" />} />
      </Route>
    </Routes>
  );
}
