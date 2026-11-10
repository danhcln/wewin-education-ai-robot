import React, { useState, useEffect } from 'react';
import {
  FileCode,
  RefreshCw,
  Search,
  Copy,
  Filter,
  CheckCircle,
  AlertTriangle,
  AlertCircle,
  Info,
  Clock,
  Terminal
} from 'lucide-react';
import { Badge } from '../components/common/Badge';
import { EmptyState } from '../components/common/EmptyState';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { LogEntry } from '../types';

export const SystemLogs: React.FC = () => {
  const { addToast } = useToast();
  const { isAuthenticated } = useAuth();
  const [loading, setLoading] = useState(true);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [filterLevel, setFilterLevel] = useState<string>('ALL');
  const [filterSource, setFilterSource] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);

  const fetchLogs = async () => {
    if (!isAuthenticated) {
      setLogs([]);
      setLoading(false);
      return;
    }
    try {
      const res = await api.getSystemLogs(100);
      setLogs(res.logs || []);
    } catch (err: any) {
      addToast({
        type: 'error',
        title: 'Lỗi tải nhật ký hệ thống',
        message: err.message
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
    if (!autoRefresh || !isAuthenticated) return;
    const interval = setInterval(fetchLogs, 10000);
    return () => clearInterval(interval);
  }, [autoRefresh, isAuthenticated]);

  const filteredLogs = logs.filter((log) => {
    if (filterLevel !== 'ALL' && log.level.toUpperCase() !== filterLevel) return false;
    if (filterSource !== 'ALL' && log.source.toLowerCase() !== filterSource.toLowerCase()) return false;
    if (searchTerm.trim()) {
      const term = searchTerm.toLowerCase();
      return (
        log.message.toLowerCase().includes(term) ||
        log.source.toLowerCase().includes(term) ||
        log.timestamp.toLowerCase().includes(term)
      );
    }
    return true;
  });

  const handleCopyLogs = () => {
    const text = filteredLogs
      .map((l) => `[${l.timestamp}] [${l.level.toUpperCase()}] [${l.source}]: ${l.message}`)
      .join('\n');
    navigator.clipboard.writeText(text);
    addToast({
      type: 'success',
      title: 'Đã sao chép nhật ký',
      message: `${filteredLogs.length} dòng log đã được chép vào clipboard.`
    });
  };

  const renderLevelBadge = (level: string) => {
    switch (level.toUpperCase()) {
      case 'ERROR':
        return <Badge variant="danger">ERROR</Badge>;
      case 'WARNING':
        return <Badge variant="warning">WARN</Badge>;
      case 'SUCCESS':
        return <Badge variant="success">SUCCESS</Badge>;
      case 'INFO':
      default:
        return <Badge variant="blue">INFO</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <FileCode className="w-7 h-7 text-[#1463E8]" />
            Nhật ký Hệ thống (System & Audit Logs)
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Ghi nhận thời gian thực các sự kiện đồng bộ website, giao tiếp MCP Bridge, và tác vụ nền.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <label className="flex items-center gap-2 text-xs font-semibold text-gray-600 bg-white px-3 py-2 rounded-xl border border-gray-200 cursor-pointer shadow-2xs">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="w-3.5 h-3.5 text-[#1463E8] rounded-xs"
            />
            Tự động làm mới (10s)
          </label>

          <button
            onClick={handleCopyLogs}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors shadow-2xs"
          >
            <Copy className="w-3.5 h-3.5 text-gray-500" />
            Sao chép
          </button>

          <button
            onClick={fetchLogs}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors shadow-xs"
          >
            <RefreshCw className={`w-4 h-4 text-gray-500 ${loading ? 'animate-spin' : ''}`} />
            Làm mới
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-white p-4 rounded-2xl border border-gray-200/90 shadow-xs flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Lọc log theo từ khóa (VD: crawler, PID, error, sync, completed)..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-4 py-2 text-xs bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:outline-hidden focus:border-[#1463E8]"
          />
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <select
            value={filterLevel}
            onChange={(e) => setFilterLevel(e.target.value)}
            className="px-3 py-2 text-xs font-semibold bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:outline-hidden text-gray-700"
          >
            <option value="ALL">Tất cả mức độ</option>
            <option value="INFO">Chỉ INFO</option>
            <option value="SUCCESS">Chỉ SUCCESS</option>
            <option value="WARNING">Chỉ WARNING</option>
            <option value="ERROR">Chỉ ERROR</option>
          </select>

          <select
            value={filterSource}
            onChange={(e) => setFilterSource(e.target.value)}
            className="px-3 py-2 text-xs font-semibold bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:outline-hidden text-gray-700"
          >
            <option value="ALL">Tất cả nguồn</option>
            <option value="sync">Đồng bộ (sync)</option>
            <option value="scheduler">Lập lịch (scheduler)</option>
            <option value="mcp">MCP Bridge</option>
            <option value="db">Cơ sở dữ liệu (db)</option>
          </select>
        </div>
      </div>

      {/* Log Terminal Window */}
      <div className="bg-gray-950 rounded-2xl border border-gray-800 shadow-xl overflow-hidden font-mono text-xs">
        {/* Terminal Header */}
        <div className="px-4 py-3 bg-gray-900 border-b border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-red-500/80"></span>
            <span className="w-3 h-3 rounded-full bg-amber-500/80"></span>
            <span className="w-3 h-3 rounded-full bg-emerald-500/80"></span>
            <span className="text-gray-400 text-[11px] ml-2 flex items-center gap-1.5 font-sans font-medium">
              <Terminal className="w-3.5 h-3.5 text-blue-400" />
              WeWIN AI System Output Stream
            </span>
          </div>

          <span className="text-[11px] text-gray-500 font-sans">
            Hiển thị {filteredLogs.length} / {logs.length} dòng
          </span>
        </div>

        {/* Terminal Body */}
        <div className="p-4 max-h-[550px] overflow-y-auto space-y-1.5 divide-y divide-gray-900/60">
          {loading ? (
            <div className="py-12 text-center text-gray-500 font-sans">
              Đang tải nhật ký từ máy chủ...
            </div>
          ) : filteredLogs.length === 0 ? (
            <div className="py-12 text-center text-gray-500 font-sans">
              Không có sự kiện nhật ký nào khớp với bộ lọc hiện tại.
            </div>
          ) : (
            filteredLogs.map((log) => (
              <div key={log.id} className="pt-1.5 flex items-start gap-3 hover:bg-gray-900/40 p-1 rounded-sm">
                <span className="text-gray-500 shrink-0 select-none text-[11px]">
                  {log.timestamp ? log.timestamp.slice(11, 19) : '--:--:--'}
                </span>

                <span className="shrink-0 scale-90 origin-left">
                  {renderLevelBadge(log.level)}
                </span>

                <span className="text-blue-400 shrink-0 font-bold text-[11px]">
                  [{log.source}]
                </span>

                <span className="text-gray-200 break-all leading-relaxed">
                  {log.message}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
