import { Navigate, Route, Routes } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import { IntakePage } from "./pages/IntakePage";
import { MetricsPage } from "./pages/MetricsPage";
import { ReplayPage } from "./pages/ReplayPage";
import { TriagePage } from "./pages/TriagePage";
import { ToastProvider } from "./toast";

export default function App() {
  return (
    <ToastProvider>
      <div className="app">
        <TopBar />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<Navigate to="/intake" replace />} />
            <Route path="/intake" element={<IntakePage />} />
            <Route path="/loop" element={<Navigate to="/intake" replace />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/triage" element={<TriagePage />} />
            <Route path="/r/:token" element={<ReplayPage />} />
            <Route path="*" element={<Navigate to="/intake" replace />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}
