import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import { AuthProvider } from "@/auth/AuthContext";
import ProtectedRoute from "@/auth/ProtectedRoute";
import AppLayout from "@/components/AppLayout";

import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import SubmitJobPage from "@/pages/SubmitJobPage";
import JobsPage from "@/pages/JobsPage";
import ProductsPage from "@/pages/ProductsPage";
import ProductDetailPage from "@/pages/ProductDetailPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import LabelsPage from "@/pages/LabelsPage";
import AccountsPage from "@/pages/AccountsPage";
import SettingsPage from "@/pages/SettingsPage";
import PLLayout from "@/pages/pl/PLLayout";
import PLDashboard from "@/pages/pl/PLDashboard";
import PLOrders from "@/pages/pl/PLOrders";
import PLSKUAnalysis from "@/pages/pl/PLSKUAnalysis";
import PLSKUCosts from "@/pages/pl/PLSKUCosts";
import PLExchangeAnalysis from "@/pages/pl/PLExchangeAnalysis";
import PLAdOrdersAnalysis from "@/pages/pl/PLAdOrdersAnalysis";
import PLUploads from "@/pages/pl/PLUploads";

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              element={
                <ProtectedRoute>
                  <AppLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<DashboardPage />} />
              <Route path="/jobs/new" element={<SubmitJobPage />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/products" element={<ProductsPage />} />
              <Route path="/products/:productId" element={<ProductDetailPage />} />
              <Route path="/analytics" element={<AnalyticsPage />} />
              <Route path="/labels" element={<LabelsPage />} />
              <Route path="/accounts" element={<AccountsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/pl" element={<PLLayout />}>
                <Route index element={<Navigate to="/pl/dashboard" replace />} />
                <Route path="dashboard" element={<PLDashboard />} />
                <Route path="orders" element={<PLOrders />} />
                <Route path="sku-analysis" element={<PLSKUAnalysis />} />
                <Route path="sku-costs" element={<PLSKUCosts />} />
                <Route path="exchange" element={<PLExchangeAnalysis />} />
                <Route path="ad-orders" element={<PLAdOrdersAnalysis />} />
                <Route path="uploads" element={<PLUploads />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </div>
  );
}

export default App;
