import { Route, Routes } from "react-router";

import { AppShell } from "./components/AppShell";
import { ClusterProvider } from "./context/ClusterProvider";
import { JobDetailPage } from "./pages/JobDetailPage";
import { HistoryPage } from "./pages/HistoryPage";
import { FilesPage } from "./pages/FilesPage";
import { JobsPage } from "./pages/JobsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SubmitJobPage } from "./pages/SubmitJobPage";
import { TopologyPage } from "./pages/TopologyPage";

export function App() {
  return (
    <ClusterProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<OverviewPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="topology" element={<TopologyPage />} />
          <Route path="files" element={<FilesPage />} />
          <Route path="jobs/submit" element={<SubmitJobPage />} />
          <Route path="jobs/:jobId" element={<JobDetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ClusterProvider>
  );
}
