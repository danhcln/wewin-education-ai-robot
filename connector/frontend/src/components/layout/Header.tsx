import React,{useEffect,useState} from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  Menu,
  Search,
  Bell,
  ShieldCheck,
  ShieldAlert,
  Radio,
  ChevronRight,
  Sparkles
} from 'lucide-react';

interface HeaderProps {
  onOpenMobileMenu: () => void;
  systemStatus?: string;
  onSearchClick?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  onOpenMobileMenu,
  systemStatus,
  onSearchClick
}) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAuthenticated, openAuthModal } = useAuth();
  const [health,setHealth]=useState('checking');
  useEffect(()=>{let active=true;const poll=async()=>{
    try{const response=await fetch('/health',{cache:'no-store',signal:AbortSignal.timeout(5000)});const data=await response.json();if(active)setHealth(response.ok&&data.status==='healthy'?'healthy':'degraded');}
    catch{if(active)setHealth('unreachable');}
  };void poll();const timer=setInterval(poll,10000);return()=>{active=false;clearInterval(timer);};},[]);
  const actualStatus=systemStatus||health;

  const routeTitles: Record<string, { title: string; subtitle: string }> = {
    '/': { title: 'Tổng quan hệ thống', subtitle: 'Bảng điều khiển robot và trợ lý AI WeWIN' },
    '/assistants': { title: 'Quản lý Trợ lý AI', subtitle: 'Cấu hình và trạng thái trợ lý AI Vietnamese' },
    '/robots': { title: 'Thiết bị & Robot', subtitle: 'Quản lý phần cứng ESP32-S3 N16R8' },
    '/knowledge': { title: 'Kho kiến thức WeWIN', subtitle: 'Cơ sở dữ liệu tìm kiếm SQLite FTS5' },
    '/sync': { title: 'Đồng bộ Website WeWIN', subtitle: 'Tự động đồng bộ nội dung công khai' },
    '/mcp-tools': { title: 'Giám sát MCP Tools', subtitle: 'Công cụ Model Context Protocol' },
    '/media': { title: 'Media Player', subtitle: 'YouTube WeWIN Education · điều khiển trình phát trên laptop' },
    '/logs': { title: 'Nhật ký Hệ thống', subtitle: 'Theo dõi audit logs và sự kiện đồng bộ' },
    '/settings': { title: 'Cài đặt hệ thống', subtitle: 'Cấu hình kết nối, bảo mật và môi trường' }
  };

  const currentRoute = routeTitles[location.pathname] || {
    title: 'WeWIN AI Control Center',
    subtitle: 'Hệ thống quản trị trợ lý AI'
  };

  return (
    <header className="sticky top-0 z-30 bg-white/90 backdrop-blur-md border-b border-slate-200/80 px-4 lg:px-8 py-3.5 flex items-center justify-between transition-all">
      {/* Left: Mobile hamburger & Titles */}
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenMobileMenu}
          className="p-2 -ml-2 rounded-xl text-slate-500 hover:text-slate-800 hover:bg-slate-100 lg:hidden"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div>
          <div className="flex items-center gap-1.5 text-[11px] text-slate-400 font-medium">
            <span className="font-semibold text-slate-600">WeWIN AI Control Center</span>
            <ChevronRight className="w-3 h-3 text-slate-300" />
            <span className="text-[#1463E8] font-medium">{currentRoute.title}</span>
          </div>
          <h1 className="text-base sm:text-lg font-bold text-slate-900 tracking-tight leading-tight">
            {currentRoute.title}
          </h1>
        </div>
      </div>

      {/* Right: Quick Search, System Status, Notification, Admin Avatar */}
      <div className="flex items-center gap-2.5 sm:gap-3.5">
        {/* Quick Search Bar */}
        <button
          onClick={onSearchClick || (() => navigate('/knowledge'))}
          className="hidden md:flex items-center gap-2 px-3.5 py-1.5 bg-slate-100/80 hover:bg-slate-100 text-slate-500 rounded-xl text-xs font-normal border border-slate-200/60 transition-colors w-48 lg:w-60"
        >
          <Search className="w-3.5 h-3.5 text-slate-400" />
          <span className="truncate">Tìm kiếm kiến thức WeWIN...</span>
          <kbd className="hidden lg:inline-block ml-auto text-[10px] bg-white border border-slate-200 text-slate-400 px-1.5 py-0.2 rounded shadow-3xs">
            /
          </kbd>
        </button>

        {/* Live System Status Pill */}
        <div className={`flex items-center gap-2 px-3 py-1.5 border rounded-full text-xs font-medium shrink-0 ${actualStatus==='healthy'?'bg-emerald-50 text-emerald-800 border-emerald-200/80':actualStatus==='unreachable'?'bg-red-50 text-red-800 border-red-200':'bg-amber-50 text-amber-800 border-amber-200'}`}>
          <span className={`w-2 h-2 rounded-full ${actualStatus==='healthy'?'bg-emerald-500':actualStatus==='unreachable'?'bg-red-500':'bg-amber-500'}`} />
          <span className="hidden sm:inline">Backend:</span> {({healthy:'Đã phản hồi',degraded:'Cần kiểm tra',unreachable:'Mất kết nối',checking:'Đang kiểm tra'} as Record<string,string>)[actualStatus]||'Chưa xác minh'}
        </div>

        {/* Admin Auth Status Button */}
        <button
          onClick={openAuthModal}
          title={isAuthenticated ? 'Quản trị viên đã xác thực' : 'Bấm để đăng nhập quản trị'}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all ${
            isAuthenticated
              ? 'bg-blue-50 border-blue-200 text-[#1463E8] hover:bg-blue-100'
              : 'bg-amber-50 border-amber-200 text-amber-700 hover:bg-amber-100'
          }`}
        >
          {isAuthenticated ? (
            <>
              <ShieldCheck className="w-4 h-4 text-[#1463E8]" />
              <span className="hidden sm:inline">Quản trị viên</span>
            </>
          ) : (
            <>
              <ShieldAlert className="w-4 h-4 text-amber-600" />
              <span className="hidden sm:inline">Chưa xác thực</span>
            </>
          )}
        </button>

        {/* Admin Avatar with WeWIN Gold Mark */}
        <div
          onClick={openAuthModal}
          title="Tài khoản Quản trị WeWIN"
          className="w-8 h-8 rounded-xl bg-white border border-slate-200 shadow-2xs flex items-center justify-center p-1 cursor-pointer hover:border-[#1463E8] transition-colors shrink-0"
        >
          <img
            src="/wewin_icon.png"
            alt="WeWIN Admin"
            className="w-full h-full object-contain"
          />
        </div>
      </div>
    </header>
  );
};
