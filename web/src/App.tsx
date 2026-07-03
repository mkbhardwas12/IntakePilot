import { Navigate, Route, Routes } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import { IntakePage } from "./pages/IntakePage";
import { MetricsPage } from "./pages/MetricsPage";
import { ToastProvider } from "./toast";

export default function App() {
  return (
    <ToastProvider>
      <div className="app">
        <TopBar />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<Navigate to="/loop" replace />} />
            <Route path="/loop" element={<IntakePage />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="*" element={<Navigate to="/loop" replace />} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}
