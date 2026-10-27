import { Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import Overview from "@/pages/Overview";
import Experiment from "@/pages/Experiment";
import ExecutionStudio from "@/pages/ExecutionStudio";
import MemoryExplorer from "@/pages/MemoryExplorer";
import ControlRoom from "@/pages/ControlRoom";
import OrchestrationLab from "@/pages/OrchestrationLab";
import ReplayLab from "@/pages/ReplayLab";
import Settings from "@/pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="experiment" element={<Experiment />} />
        <Route path="runs" element={<ExecutionStudio />} />
        <Route path="runs/:runId" element={<ExecutionStudio />} />
        <Route path="memory" element={<MemoryExplorer />} />
        <Route path="control" element={<ControlRoom />} />
        <Route path="orchestration" element={<OrchestrationLab />} />
        <Route path="orchestration/:workflowId" element={<OrchestrationLab />} />
        <Route path="replay" element={<ReplayLab />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Overview />} />
      </Route>
    </Routes>
  );
}
