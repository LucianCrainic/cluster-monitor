import { Route, Routes } from "react-router";

import { AppShell } from "./components/AppShell";
import { ClusterProvider } from "./context/ClusterProvider";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobsPage } from "./pages/JobsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SubmitJobPage } from "./pages/SubmitJobPage";

export function App() {
  return (
    <ClusterProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<OverviewPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="jobs/submit" element={<SubmitJobPage />} />
          <Route path="jobs/:jobId" element={<JobDetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ClusterProvider>
  );
}
