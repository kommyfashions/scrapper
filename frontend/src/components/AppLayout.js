import { Outlet } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import AlertsBell from "@/components/AlertsBell";

export default function AppLayout() {
  return (
    <div className="flex h-screen w-full bg-[#0A0A0A] text-white">
      <Sidebar />
      <main className="flex-1 overflow-y-auto relative">
        <div className="fixed top-4 right-6 z-30">
          <AlertsBell />
        </div>
        <Outlet />
      </main>
    </div>
  );
}
