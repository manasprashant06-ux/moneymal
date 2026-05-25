import { useState, createContext, useContext } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import useAnalysis from './hooks/useAnalysis';
import Navbar from './components/Navbar';
import LandingPage from './pages/LandingPage';
import Dashboard from './pages/Dashboard';
import GraphPage from './pages/GraphPage';
import TransactionsPage from './pages/TransactionsPage';
import RiskAnalysisPage from './pages/RiskAnalysisPage';
import Toast from './components/Toast';

export const AppContext = createContext(null);

export function useAppContext() {
  return useContext(AppContext);
}

export default function App() {
  const analysis = useAnalysis();
  const [file, setFile] = useState(null);
  const [toast, setToast] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);

  const showToast = (message, type = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  const ctx = {
    ...analysis,
    file,
    setFile,
    selectedNode,
    setSelectedNode,
    showToast,
  };

  return (
    <AppContext.Provider value={ctx}>
      <BrowserRouter>
        {analysis.result && <Navbar />}
        <Routes>
          <Route path="/" element={analysis.result ? <Dashboard /> : <LandingPage />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/transactions" element={<TransactionsPage />} />
          <Route path="/risk" element={<RiskAnalysisPage />} />
        </Routes>
        {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
      </BrowserRouter>
    </AppContext.Provider>
  );
}
