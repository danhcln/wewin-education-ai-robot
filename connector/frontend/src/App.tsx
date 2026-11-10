import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ToastProvider } from './context/ToastContext';
import { AuthProvider } from './context/AuthContext';
import { Layout } from './components/layout/Layout';

import { DashboardOverview } from './pages/DashboardOverview';
import { AIAssistants } from './pages/AIAssistants';
import { RobotManagement } from './pages/RobotManagement';
import { KnowledgeManager } from './pages/KnowledgeManager';
import { AutoSyncManager } from './pages/AutoSyncManager';
import { MCPToolsMonitor } from './pages/MCPToolsMonitor';
import { SystemLogs } from './pages/SystemLogs';
import { SettingsPage } from './pages/SettingsPage';
import { MediaPlayer } from './pages/MediaPlayer';

export function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<DashboardOverview />} />
              <Route path="/assistants" element={<AIAssistants />} />
              <Route path="/robots" element={<RobotManagement />} />
              <Route path="/knowledge" element={<KnowledgeManager />} />
              <Route path="/sync" element={<AutoSyncManager />} />
              <Route path="/mcp-tools" element={<MCPToolsMonitor />} />
              <Route path="/logs" element={<SystemLogs />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/media" element={<MediaPlayer />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  );
}

export default App;
