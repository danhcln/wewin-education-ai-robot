import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Bot,
  Cpu,
  BookOpen,
  RefreshCw,
  Wrench,
  Terminal,
  Settings,
  Sparkles,
  ExternalLink,
  Video
} from 'lucide-react';

interface SidebarProps {
  isMobileOpen: boolean;
  onCloseMobile: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ isMobileOpen, onCloseMobile }) => {
  const navItems = [
    { to: '/', label: 'Tổng quan', icon: LayoutDashboard },
    { to: '/assistants', label: 'Trợ lý AI', icon: Bot },
    { to: '/robots', label: 'Thiết bị / Robot', icon: Cpu },
    { to: '/knowledge', label: 'Kho kiến thức', icon: BookOpen },
    { to: '/sync', label: 'Đồng bộ website', icon: RefreshCw },
    { to: '/mcp-tools', label: 'MCP Tools', icon: Wrench },
    { to: '/media', label: 'Media Player', icon: Video },
    { to: '/logs', label: 'Nhật ký hệ thống', icon: Terminal },
    { to: '/settings', label: 'Cài đặt', icon: Settings }
  ];

  return (
    <>
      {/* Mobile Backdrop */}
      {isMobileOpen && (
        <div
          onClick={onCloseMobile}
          className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-xs lg:hidden"
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`fixed top-0 bottom-0 left-0 z-40 w-64 bg-white border-r border-slate-200/80 flex flex-col transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          isMobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand Header */}
        <div className="px-5 py-4.5 border-b border-slate-100/90 bg-white">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-slate-50/80 border border-slate-200/80 p-1.5 flex items-center justify-center shadow-2xs shrink-0">
              <img
                src="/wewin_icon.png"
                alt="WeWIN Education"
                className="w-full h-full object-contain"
              />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-bold text-slate-900 tracking-tight leading-tight">
                  WeWIN AI
                </span>
                <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-blue-50 text-[#1463E8] border border-blue-200/60 rounded">
                  v1.0
                </span>
              </div>
              <p className="text-[11px] font-semibold text-[#1463E8] truncate mt-0.5">
                Control Center
              </p>
            </div>
          </div>
          <div className="mt-3 pt-2 border-t border-slate-100 flex items-center justify-between">
            <img
              src="/wewin_logo.png"
              alt="WeWIN Education"
              className="h-4.5 w-auto object-contain opacity-95"
            />
            <span className="text-[10px] text-slate-400 font-medium">Trung tâm Ngoại ngữ</span>
          </div>
        </div>

        {/* Navigation Menu */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <div className="px-3 pb-2 text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
            Menu Quản Trị
          </div>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                onClick={onCloseMobile}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-medium transition-all ${
                    isActive
                      ? 'bg-blue-600 text-white shadow-sm font-semibold shadow-blue-500/20'
                      : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/80'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-white' : 'text-slate-500'}`} />
                    <span className="truncate">{item.label}</span>
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>

        {/* Bottom Robot Widget */}
        <div className="p-3 border-t border-slate-100 bg-slate-50/60 m-3 rounded-2xl border">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center text-blue-600 shrink-0 relative">
              <Cpu className="w-4 h-4" />
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-slate-400 " />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-slate-800 truncate">ESP32-S3 Robot</p>
              <p className="text-[10px] text-emerald-600 font-medium flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                XiaoZhi: Unknown
              </p>
            </div>
          </div>
          <a
            href="https://wewin.edu.vn"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-1.5 w-full py-1.5 text-[11px] font-medium text-slate-500 hover:text-blue-600 bg-white border border-slate-200/80 rounded-xl hover:border-blue-300 shadow-2xs transition-colors"
          >
            <span>wewin.edu.vn</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      </aside>
    </>
  );
};
