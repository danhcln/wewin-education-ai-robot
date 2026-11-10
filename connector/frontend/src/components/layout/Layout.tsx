import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { AuthModal } from '../common/AuthModal';

export const Layout: React.FC = () => {
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[#F7FAFF] flex flex-col font-sans">
      <Sidebar
        isMobileOpen={isMobileOpen}
        onCloseMobile={() => setIsMobileOpen(false)}
      />

      <div className="lg:pl-64 flex flex-col flex-1 min-w-0">
        <Header onOpenMobileMenu={() => setIsMobileOpen(true)} />

        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </main>

        <footer className="py-4 px-6 border-t border-slate-200/60 bg-white/50 text-center text-[11px] text-slate-400">
          WeWIN AI Control Center v1.0.0 &copy; 2026 WeWIN Education. Tích hợp XiaoZhi AI & ESP32-S3.
        </footer>
      </div>

      <AuthModal />
    </div>
  );
};
