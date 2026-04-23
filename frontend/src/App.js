import React, { useEffect } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";

import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import JobDetail from "@/pages/JobDetail";
import ProtectedRoute from "@/components/ProtectedRoute";

function App() {
  // Force dark mode globally (no light toggle).
  useEffect(() => {
    document.documentElement.classList.add("dark");
    document.documentElement.style.colorScheme = "dark";
  }, []);

  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/jobs/:id"
            element={
              <ProtectedRoute>
                <JobDetail />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <Toaster
          theme="dark"
          position="top-right"
          toastOptions={{
            style: {
              background: "#0a0a0a",
              border: "1px solid #262626",
              color: "#f5f5f5",
            },
          }}
        />
      </BrowserRouter>
    </div>
  );
}

export default App;
