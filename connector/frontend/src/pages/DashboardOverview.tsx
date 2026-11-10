import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { DashboardStats } from '../types';
import { StatCard } from '../components/common/StatCard';
import { Badge } from '../components/common/Badge';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import {
  Activity,
  Bot,
  Cpu,
  BookOpen,
  RefreshCw,
  Clock,
  Sparkles,
  ArrowRight,
  Search,
  CheckCircle2,
  Calendar,
  Layers,
  Zap,
  ExternalLink
} from 'lucide-react';

export const DashboardOverview: React.FC = () => {
  const navigate = useNavigate();
  const toast = useToast();
  const { isAuthenticated } = useAuth();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);

  useEffect(() => {
    loadDashboardData();
  }, [isAuthenticated]);

  const loadDashboardData = async () => {
    if (!isAuthenticated) {
      setStats(null);
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await api.getDashboardStats();
      setStats(data);
    } catch (err: any) {
      toast.error('Không thể tải dữ liệu thống kê từ Backend: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleQuickSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    try {
      const res = await api.searchKnowledge(searchQuery.trim(), 3);
      setSearchResults(res.results);
      if (res.results.length === 0) {
        toast.info(`Không tìm thấy kết quả nào cho '${searchQuery}'`);
      }
    } catch (err: any) {
      toast.error('Lỗi tìm kiếm: ' + err.message);
    } finally {
      setIsSearching(false);
    }
  };

  const dbStats = stats?.database;
  const syncStats = stats?.sync_engine;
  const mcpStats = stats?.mcp_bridge;
  const lastSync = syncStats?.last_sync;

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* 1. EXECUTIVE WEWIN AI HERO BANNER */}
      <div className="relative overflow-hidden rounded-3xl bg-linear-to-br from-[#123B86] via-[#1463E8] to-[#0A2E6E] text-white p-7 sm:p-9 shadow-lg shadow-blue-900/15 border border-blue-400/20">
        {/* Subtle Tech Geometric Grid Overlay */}
        <div
          className="absolute inset-0 opacity-[0.04] pointer-events-none"
          style={{
            backgroundImage:
              'radial-gradient(circle at 1px 1px, white 1px, transparent 0)',
            backgroundSize: '24px 24px'
          }}
        />

        <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-8">
          {/* Left Column: Heading, Description, Action Buttons */}
          <div className="max-w-2xl space-y-4">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/12 backdrop-blur-md text-xs font-semibold border border-white/20">
              <span className="w-2 h-2 rounded-full bg-amber-400"></span>
              <span className="text-blue-100">WeWIN Education</span>
              <span className="text-white/40">&bull;</span>
              <span className="text-amber-300 font-medium">Trung tâm Ngoại ngữ Công Thành</span>
            </div>

            <h2 className="text-2xl sm:text-3xl lg:text-4xl font-extrabold tracking-tight leading-tight">
              WeWIN AI Control Center
            </h2>

            <p className="text-xs sm:text-sm text-blue-100 font-normal leading-relaxed max-w-xl">
              Hệ thống quản trị và điều phối tập trung dành cho robot thông minh ESP32-S3 và trợ lý tiếng nói WeWIN Education. Tự động đồng bộ tri thức từ website wewin.edu.vn phục vụ tư vấn học viên và phụ huynh.
            </p>

            <div className="pt-2 flex flex-wrap items-center gap-3">
              <button
                onClick={() => navigate('/sync')}
                className="inline-flex items-center gap-2 px-4.5 py-2.5 rounded-xl bg-white text-[#123B86] text-xs font-bold shadow-md hover:bg-blue-50 transition-all active:scale-95"
              >
                <RefreshCw className="w-4 h-4 text-[#1463E8]" />
                <span>Đồng bộ Website ngay</span>
              </button>

              <button
                onClick={() => navigate('/knowledge')}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/12 hover:bg-white/20 text-white text-xs font-semibold border border-white/25 backdrop-blur-xs transition-all"
              >
                <BookOpen className="w-4 h-4" />
                <span>Kho kiến thức FTS5</span>
              </button>

              <button
                onClick={() => navigate('/mcp-tools')}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/12 hover:bg-white/20 text-white text-xs font-semibold border border-white/25 backdrop-blur-xs transition-all"
              >
                <Zap className="w-4 h-4 text-amber-300" />
                <span>Giám sát MCP Tools</span>
              </button>
            </div>
          </div>

          {/* Right Column: Live Infrastructure Telemetry Card */}
          <div className="w-full lg:w-80 shrink-0 bg-white/10 backdrop-blur-md rounded-2xl border border-white/20 p-5 shadow-inner space-y-3">
            <div className="flex items-center justify-between pb-2.5 border-b border-white/15">
              <span className="text-xs font-bold uppercase tracking-wider text-blue-200">
                Hạ tầng thời gian thực
              </span>
              <span className="flex items-center gap-1.5 text-[11px] font-bold text-emerald-300">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                {stats?.backend_status === 'healthy' ? 'Backend đã phản hồi' : 'Unknown'}
              </span>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between py-1">
                <span className="text-blue-100 flex items-center gap-2">
                  <Activity className="w-3.5 h-3.5 text-blue-300" />
                  FastAPI Backend:
                </span>
                <span className="font-mono font-semibold text-white">{stats?.backend_status === 'healthy' ? 'Healthy' : 'Unknown'}</span>
              </div>

              <div className="flex items-center justify-between py-1">
                <span className="text-blue-100 flex items-center gap-2">
                  <Cpu className="w-3.5 h-3.5 text-blue-300" />
                  Robot ESP32-S3:
                </span>
                <span className="font-semibold text-emerald-300">Unknown — chưa có heartbeat</span>
              </div>

              <div className="flex items-center justify-between py-1">
                <span className="text-blue-100 flex items-center gap-2">
                  <Zap className="w-3.5 h-3.5 text-amber-300" />
                  MCP Bridge:
                </span>
                <span className="font-semibold text-white">{mcpStats?.connection_status || 'unknown'}</span>
              </div>

              <div className="flex items-center justify-between py-1">
                <span className="text-blue-100 flex items-center gap-2">
                  <Calendar className="w-3.5 h-3.5 text-blue-300" />
                  Auto-Sync Task:
                </span>
                <span className="font-mono text-white text-[11px]">{syncStats?.auto_sync_enabled ? '08:00 & 20:00 (cấu hình)' : 'Disabled'}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Ambient background glows */}
        <div className="absolute -top-24 -right-24 w-96 h-96 rounded-full bg-blue-400/10 blur-3xl pointer-events-none" />
        <div className="absolute -bottom-24 left-1/3 w-80 h-80 rounded-full bg-indigo-500/10 blur-3xl pointer-events-none" />
      </div>

      {/* 2. KEY METRICS CARDS */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-5">
        <StatCard
          title="Backend FastAPI"
          value={stats?.backend_status === 'healthy' ? 'Hoạt động tốt' : 'Đang kiểm tra...'}
          subValue="Port 8000 &bull; SQLite FTS5"
          icon={Activity}
          iconColor="text-emerald-600"
          iconBg="bg-emerald-50"
          badgeText={stats ? `Uptime backend: ${stats.uptime_seconds}s` : 'Unknown'}
          badgeVariant="success"
          onClick={() => navigate('/settings')}
        />

        <StatCard
          title="XiaoZhi MCP Bridge"
          value={mcpStats?.connection_status || 'unknown'}
          subValue={`${mcpStats?.tools_registered || 5} công cụ được khai báo`}
          icon={Bot}
          iconColor="text-blue-600"
          iconBg="bg-blue-50"
          badgeText="Trạng thái từ bridge riêng"
          badgeVariant="primary"
          onClick={() => navigate('/mcp-tools')}
        />

        <StatCard
          title="Robot ESP32-S3"
          value={`${stats?.robots.length || 1} Thiết bị`}
          subValue="ESP32-S3 N16R8 &bull; INMP441 &bull; SSD1306"
          icon={Cpu}
          iconColor="text-indigo-600"
          iconBg="bg-indigo-50"
          badgeText="AI Vietnamese"
          badgeVariant="success"
          onClick={() => navigate('/robots')}
        />

        <StatCard
          title="Kho Kiến Thức WeWIN"
          value={`${dbStats?.total_pages || 0} Trang`}
          subValue={`${dbStats?.seed_pages || 0} hạt mầm &bull; ${dbStats?.scraped_pages || 0} trang web`}
          icon={BookOpen}
          iconColor="text-amber-600"
          iconBg="bg-amber-50"
          badgeText={`${dbStats?.public_searchable ?? 0} trang phục vụ công khai`}
          badgeVariant="warning"
          onClick={() => navigate('/knowledge')}
        />

        <StatCard
          title="Lần Đồng Bộ Gần Nhất"
          value={lastSync?.status ? lastSync.status.toUpperCase() : 'CHƯA ĐỒNG BỘ'}
          subValue={lastSync ? `Đã thêm: +${lastSync.pages_added} | Bỏ qua: ${lastSync.pages_skipped || 0}` : 'Sẵn sàng'}
          icon={Clock}
          iconColor="text-purple-600"
          iconBg="bg-purple-50"
          badgeText={lastSync ? `${lastSync.duration_seconds}s` : '0s'}
          badgeVariant={lastSync?.status === 'success' ? 'success' : 'warning'}
          onClick={() => navigate('/sync')}
        />

        <StatCard
          title="Lịch Trình Auto-Sync"
          value="08:00 & 20:00"
          subValue={`Lần kế tiếp: ${syncStats?.next_scheduled_run || 'Unknown'}`}
          icon={Calendar}
          iconColor="text-cyan-600"
          iconBg="bg-cyan-50"
          badgeText={syncStats?.auto_sync_enabled ? 'Lịch đã cấu hình; cần xác minh owner' : 'Lịch đang tắt'}
          badgeVariant="success"
          onClick={() => navigate('/sync')}
        />
      </div>

      {/* 3. MIDDLE ROW: KNOWLEDGE CATEGORIES & LIVE QUICK SEARCH */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Category Breakdown (2 cols) */}
        <div className="lg:col-span-2 bg-white rounded-2xl p-6 border border-slate-200/80 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-slate-900 tracking-tight flex items-center gap-2">
                <Layers className="w-4 h-4 text-blue-600" />
                <span>Phân Bố Kho Kiến Thức Theo Danh Mục</span>
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Các chuyên đề nội dung đã lập chỉ mục từ website wewin.edu.vn
              </p>
            </div>
            <button
              onClick={() => navigate('/knowledge')}
              className="text-xs font-semibold text-blue-600 hover:text-blue-700 flex items-center gap-1"
            >
              <span>Xem tất cả</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Object.entries(stats?.categories_distribution || {}).map(([cat, count]) => (
              <div
                key={cat}
                onClick={() => navigate(`/knowledge?category=${cat}`)}
                className="p-3.5 rounded-xl border border-slate-100 bg-slate-50/70 hover:bg-blue-50/60 hover:border-blue-200 transition-all cursor-pointer group"
              >
                <div className="text-[11px] font-medium text-slate-500 uppercase tracking-wider group-hover:text-blue-700">
                  {cat}
                </div>
                <div className="text-xl font-bold text-slate-900 mt-1 group-hover:text-blue-800">
                  {count} <span className="text-xs font-normal text-slate-400">bài</span>
                </div>
              </div>
            ))}
          </div>

          {/* Core URL Highlights */}
          <div className="mt-5 pt-4 border-t border-slate-100 flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-500 font-medium">Trang ưu tiên:</span>
            <span className="text-[11px] px-2.5 py-1 rounded-md bg-blue-50 text-blue-700 font-medium border border-blue-100">
              Trang chủ WeWIN (NFC)
            </span>
            <span className="text-[11px] px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 font-medium border border-emerald-100">
              Cambridge Starters/Movers/Flyers
            </span>
            <span className="text-[11px] px-2.5 py-1 rounded-md bg-purple-50 text-purple-700 font-medium border border-purple-100">
              IELTS Explorer (IDP)
            </span>
            <span className="text-[11px] px-2.5 py-1 rounded-md bg-amber-50 text-amber-700 font-medium border border-amber-100">
              Hotlines &amp; 2 Cơ sở Bình Thạnh
            </span>
          </div>
        </div>

        {/* Live Quick Search Tester (1 col) */}
        <div className="bg-white rounded-2xl p-6 border border-slate-200/80 shadow-sm flex flex-col">
          <div className="mb-4">
            <h3 className="text-sm font-bold text-slate-900 tracking-tight flex items-center gap-2">
              <Search className="w-4 h-4 text-blue-600" />
              <span>Tìm Kiếm Nhanh FTS5</span>
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Thử nghiệm độ nhạy SQLite FTS5 trước khi XiaoZhi gọi
            </p>
          </div>

          <form onSubmit={handleQuickSearch} className="mb-4">
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="VD: IELTS, Cambridge, học phí, hotline..."
                className="w-full pl-3.5 pr-20 py-2.5 text-xs bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
              />
              <button
                type="submit"
                disabled={isSearching}
                className="absolute right-1.5 top-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {isSearching ? '...' : 'Tìm'}
              </button>
            </div>
          </form>

          {/* Quick results preview */}
          <div className="flex-1 space-y-2 overflow-y-auto max-h-56">
            {searchResults.length > 0 ? (
              searchResults.map((r, idx) => (
                <div key={idx} className="p-2.5 rounded-xl bg-slate-50 border border-slate-100 text-xs">
                  <div className="font-semibold text-slate-800 truncate">{r.title}</div>
                  <div className="text-[11px] text-slate-500 mt-0.5 line-clamp-2">{r.snippet}</div>
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[10px] text-blue-600 hover:underline mt-1 inline-flex items-center gap-1"
                  >
                    <span>{r.url}</span>
                    <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                </div>
              ))
            ) : (
              <div className="text-center py-6 text-xs text-slate-400">
                Nhập từ khóa và bấm Tìm để kiểm tra kết quả xếp hạng BM25 tức thì.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 4. RECENT SYNC ACTIVITY TIMELINE */}
      <div className="bg-white rounded-2xl p-6 border border-slate-200/80 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-slate-900 tracking-tight flex items-center gap-2">
              <RefreshCw className="w-4 h-4 text-blue-600" />
              <span>Hoạt Động Đồng Bộ Gần Đây</span>
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Lịch sử các phiên quét tự động và thủ công
            </p>
          </div>
          <button
            onClick={() => navigate('/sync')}
            className="text-xs font-semibold text-blue-600 hover:text-blue-700 flex items-center gap-1"
          >
            <span>Chi tiết đồng bộ</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-slate-400 font-semibold text-[11px] uppercase tracking-wider">
                <th className="pb-3 pl-2">Thời gian</th>
                <th className="pb-3">Trạng thái</th>
                <th className="pb-3">Nguồn kích hoạt</th>
                <th className="pb-3">Thời lượng</th>
                <th className="pb-3">Trang thêm mới</th>
                <th className="pb-3">Trang cập nhật</th>
                <th className="pb-3">Bỏ qua / Seed Guard</th>
                <th className="pb-3">Con trỏ Cursor</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-600">
              {(stats?.recent_syncs || []).map((sync) => (
                <tr key={sync.id} className="hover:bg-slate-50/80 transition-colors">
                  <td className="py-3 pl-2 font-mono text-[11px] text-slate-700">
                    {new Date(sync.started_at).toLocaleString('vi-VN')}
                  </td>
                  <td className="py-3">
                    <Badge
                      variant={
                        sync.status === 'success'
                          ? 'success'
                          : sync.status === 'partial'
                          ? 'warning'
                          : 'danger'
                      }
                      size="sm"
                    >
                      {sync.status.toUpperCase()}
                    </Badge>
                  </td>
                  <td className="py-3 font-medium text-slate-800">
                    {sync.trigger_type === 'task_scheduler'
                      ? 'Windows Task Scheduler'
                      : sync.trigger_type}
                  </td>
                  <td className="py-3">{sync.duration_seconds}s</td>
                  <td className="py-3 text-emerald-600 font-semibold">+{sync.pages_added}</td>
                  <td className="py-3 text-blue-600 font-semibold">{sync.pages_updated}</td>
                  <td className="py-3 text-slate-500">{sync.pages_skipped || 0}</td>
                  <td className="py-3 font-mono text-slate-700">{sync.crawl_cursor || 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
