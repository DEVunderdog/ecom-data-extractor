import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { isAuthed } from "@/lib/api";

export default function ProtectedRoute({ children }) {
  const location = useLocation();
  if (!isAuthed()) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
}
