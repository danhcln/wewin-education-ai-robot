import React, { useState, useEffect } from 'react';
import {
  RefreshCw,
  Clock,
  Calendar,
  CheckCircle2,
  AlertTriangle,
  Play,
  RotateCcw,
  Sparkles,
  ShieldCheck,
  Zap,
  Layers,
  Unlock,
  AlertCircle
} from 'lucide-react';
import { Badge } from '../components/common/Badge';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { SyncReportResult } from '../types';

export const AutoSyncManager: React.FC = () => {
  const { addToast } = useToast();
  const { requireAdmin, isAuthenticated } = useAuth();
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [statusData, setStatusData] = useState<any>(null);
  const [historyData, setHistoryData] = useState<any[]>([]);
  const [batchSize, setBatchSize] = useState<number>(25);
  const [syncAll, setSyncAll] = useState<boolean>(false);
  const [dryRun, setDryRun] = useState<boolean>(false);
  const [latestReport, setLatestReport] = useState<SyncReportResult | null>(null);

  const fetchSyncData = async () => {
    if (!isAuthenticated) {
      setStatusData(null);
      setHistoryData([]);
      setLatestReport(null);
      setLoading(false);
      return;
    }
    try {
      const [status, history] = await Promise.all([
        api.getSyncStatus().catch(() => null),
        api.getSyncHistory(15).catch(() => ({ history: [] }))
      ]);
      setStatusData(status);
      setHistoryData(history.history || []);
    } catch (err: any) {
      addToast({
        type: 'error',
        title: 'Lỗi tải trạng thái đồng bộ',
        message: err.message || 'Không thể đọc thông tin từ backend.'
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSyncData();
    if (!isAuthenticated) return;
    const interval = setInterval(fetchSyncData, 15000); // Poll status every 15s
    return () => clearInterval(interval);
  }, [isAuthenticated]);

  const handleTriggerSync = async () => {
    requireAdmin(async () => {
      setSyncing(true);
      try {
        addToast({
          type: 'info',
          title: 'Đang khởi chạy tiến trình đồng bộ...',
          message: `Đang quét và đồng bộ dữ liệu từ wewin.edu.vn (${syncAll ? 'Toàn bộ trang' : `Batch ${batchSize} trang`}).`
        });

        const res = await api.triggerSync({
          maxPages: syncAll ? undefined : batchSize,
          allPages: syncAll,
          dryRun: dryRun
        });

        if (res.success) {
          setLatestReport(res.report);
          addToast({
            type: 'success',
            title: 'Đồng bộ hoàn tất thành công!',
            message: `Thêm mới: ${res.report?.pages_added || 0}, Cập nhật: ${res.report?.pages_updated || 0}, Không đổi: ${res.report?.pages_unchanged || 0}.`
          });
          fetchSyncData();
        } else {
          addToast({
            type: 'warning',
            title: 'Tiến trình kết thúc với cảnh báo',
            message: res.message
          });
        }
      } catch (err: any) {
        addToast({
          type: 'error',
          title: 'Lỗi khởi chạy đồng bộ',
          message: err.message || 'Có lỗi xảy ra trong quá trình gọi API /sync.'
        });
      } finally {
        setSyncing(false);
      }
    });
  };

  const handleUnlockLock = async () => {
    requireAdmin(async () => {
      try {
        const res = await api.unlockSync();
        addToast({
          type: 'success',
          title: 'Đã giải phóng khóa đồng bộ',
          message: res.message
        });
        fetchSyncData();
      } catch (err: any) {
        addToast({
          type: 'error',
          title: 'Lỗi giải phóng khóa',
          message: err.message
        });
      }
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <RefreshCw className="w-7 h-7 text-[#1463E8]" />
            Đồng bộ Website Tự động (Auto-Sync Engine)
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Động cơ tự động quét sitemap và thu thập nội dung mới từ https://wewin.edu.vn/ định kỳ theo lịch Windows Task Scheduler.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          {statusData?.is_syncing && (
            <button
              onClick={handleUnlockLock}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-rose-700 bg-rose-50 border border-rose-200 rounded-xl hover:bg-rose-100 transition-colors shadow-2xs"
            >
              <Unlock className="w-3.5 h-3.5" />
              Giải phóng khóa kẹt
            </button>
          )}

          <button
            onClick={fetchSyncData}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors shadow-xs"
          >
            <RotateCcw className="w-4 h-4 text-gray-500" />
            Làm mới
          </button>
        </div>
      </div>

      {/* Schedule Banner */}
      <div className="p-5 rounded-2xl bg-gradient-to-r from-blue-900 via-[#1463E8] to-[#123B86] text-white shadow-md relative overflow-hidden">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-white/20 text-white text-xs font-semibold backdrop-blur-xs">
              <Calendar className="w-3.5 h-3.5 text-amber-300" />
              Lịch trình tự động kích hoạt
            </div>
            <h2 className="text-xl font-bold">Windows Task Scheduler: 08:00 & 20:00 hằng ngày</h2>
            <p className="text-xs text-blue-100 max-w-2xl leading-relaxed">
              Tác vụ "WeWIN_Website_AutoSync" chạy hoàn toàn tự động ở chế độ nền trên máy chủ, sử dụng cơ chế xoay vòng con trỏ crawl để bao phủ toàn bộ 515+ URL sitemap của WeWIN Education.
            </p>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <div className="text-right">
              <div className="text-[11px] text-blue-200">Trạng thái khóa tiến trình:</div>
              <div className="text-sm font-bold flex items-center justify-end gap-1.5 mt-0.5">
                {statusData?.is_syncing ? (
                  <span className="flex items-center gap-1.5 text-amber-300">
                    <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping"></span>
                    Đang chạy tiến trình
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-emerald-300">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    Sẵn sàng (Lock rỗi)
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
        <div className="p-4 bg-white rounded-2xl border border-gray-200/90 shadow-xs">
          <div className="text-xs text-gray-500 font-medium">Sitemap URL</div>
          <div className="text-xl font-bold text-gray-900 mt-1">515</div>
          <div className="text-[11px] text-blue-600 mt-0.5">Đã phân tích</div>
        </div>

        <div className="p-4 bg-white rounded-2xl border border-gray-200/90 shadow-xs">
          <div className="text-xs text-gray-500 font-medium">URL hợp lệ</div>
          <div className="text-xl font-bold text-gray-900 mt-1">440</div>
          <div className="text-[11px] text-emerald-600 mt-0.5">Đủ điều kiện cào</div>
        </div>

        <div className="p-4 bg-white rounded-2xl border border-gray-200/90 shadow-xs">
          <div className="text-xs text-gray-500 font-medium">Trang đã lưu DB</div>
          <div className="text-xl font-bold text-gray-900 mt-1">
            {statusData ? statusData.total_pages : '...'}
          </div>
          <div className="text-[11px] text-gray-500 mt-0.5">
            {statusData ? `${statusData.seed_pages} seeds, ${statusData.scraped_pages} web` : ''}
          </div>
        </div>

        <div className="p-4 bg-white rounded-2xl border border-gray-200/90 shadow-xs">
          <div className="text-xs text-gray-500 font-medium">Con trỏ Cursor</div>
          <div className="text-xl font-bold text-indigo-600 mt-1">
            {statusData ? statusData.crawl_cursor : 0}
          </div>
          <div className="text-[11px] text-gray-500 mt-0.5">Vị trí đợt tiếp theo</div>
        </div>

        <div className="p-4 bg-white rounded-2xl border border-gray-200/90 shadow-xs">
          <div className="text-xs text-gray-500 font-medium">Lần chạy gần nhất</div>
          <div className="text-xs font-bold text-gray-800 mt-1 line-clamp-1">
            {statusData?.last_sync ? statusData.last_sync.slice(11, 19) : '08:00'}
          </div>
          <div className="text-[11px] text-emerald-600 mt-0.5">
            {statusData?.last_sync ? statusData.last_sync.slice(0, 10) : 'Hôm nay'}
          </div>
        </div>

        <div className="p-4 bg-white rounded-2xl border border-gray-200/90 shadow-xs">
          <div className="text-xs text-gray-500 font-medium">Cơ chế an toàn</div>
          <div className="text-xs font-bold text-emerald-700 mt-1 flex items-center gap-1">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            PID Concurrency
          </div>
          <div className="text-[11px] text-gray-500 mt-0.5">Auto-release stale</div>
        </div>
      </div>

      {/* Manual Sync Control Panel */}
      <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-gray-100">
          <div>
            <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
              <Zap className="w-5 h-5 text-[#1463E8]" />
              Kích hoạt Đồng bộ Ngay (Manual Sync Trigger)
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Cho phép quản trị viên kích hoạt ngay lập tức tiến trình thu thập dữ liệu mới mà không cần chờ tới 08:00 hoặc 20:00.
            </p>
          </div>

          <button
            onClick={handleTriggerSync}
            disabled={syncing || statusData?.is_syncing}
            className="inline-flex items-center justify-center gap-2 px-6 py-2.5 text-sm font-bold text-white bg-[#1463E8] hover:bg-[#123B86] disabled:opacity-50 disabled:pointer-events-none rounded-xl transition-all shadow-md shadow-blue-500/20 active:scale-95 shrink-0"
          >
            {syncing ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Đang thu thập dữ liệu...
              </>
            ) : (
              <>
                <Play className="w-4 h-4 fill-white" />
                Đồng bộ ngay bây giờ
              </>
            )}
          </button>
        </div>

        {/* Sync Options Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-5">
          <div className="space-y-1.5">
            <label className="block text-xs font-bold text-gray-700">Chế độ phân trang (Batching)</label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSyncAll(false)}
                className={`flex-1 py-2 px-3 text-xs font-semibold rounded-xl border transition-all ${
                  !syncAll ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-gray-50 border-gray-200 text-gray-600'
                }`}
              >
                Theo đợt (Khuyên dùng)
              </button>
              <button
                type="button"
                onClick={() => setSyncAll(true)}
                className={`flex-1 py-2 px-3 text-xs font-semibold rounded-xl border transition-all ${
                  syncAll ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-gray-50 border-gray-200 text-gray-600'
                }`}
              >
                Toàn bộ sitemap
              </button>
            </div>
          </div>

          {!syncAll && (
            <div className="space-y-1.5">
              <label className="block text-xs font-bold text-gray-700">Số lượng trang trong đợt này</label>
              <select
                value={batchSize}
                onChange={(e) => setBatchSize(Number(e.target.value))}
                className="w-full py-2 px-3 text-xs font-semibold bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:outline-hidden focus:border-[#1463E8]"
              >
                <option value={15}>15 trang (Nhanh)</option>
                <option value={25}>25 trang (Mặc định)</option>
                <option value={50}>50 trang</option>
                <option value={100}>100 trang (Chuyên sâu)</option>
              </select>
            </div>
          )}

          <div className="space-y-1.5">
            <label className="block text-xs font-bold text-gray-700">Chế độ mô phỏng (Dry-run)</label>
            <label className="flex items-center gap-2.5 p-2 bg-gray-50 border border-gray-200 rounded-xl cursor-pointer hover:bg-gray-100 transition-colors">
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(e) => setDryRun(e.target.checked)}
                className="w-4 h-4 text-[#1463E8] rounded-sm focus:ring-blue-500"
              />
              <span className="text-xs text-gray-700 font-medium">Chỉ kiểm tra thay đổi, không ghi đè DB</span>
            </label>
          </div>
        </div>

        {/* Real-time result card if sync was just run */}
        {latestReport && (
          <div className="mt-5 p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-900 animate-in fade-in duration-200">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-800 flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                Kết quả đợt đồng bộ vừa thực hiện:
              </span>
              <span className="text-xs font-mono font-medium text-emerald-700">
                Thời gian: {latestReport.duration_seconds?.toFixed(1)}s
              </span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
              <div className="p-2 bg-white/80 rounded-lg">
                <div className="text-gray-500">Thêm mới:</div>
                <div className="text-sm font-bold text-emerald-700">{latestReport.pages_added}</div>
              </div>
              <div className="p-2 bg-white/80 rounded-lg">
                <div className="text-gray-500">Cập nhật:</div>
                <div className="text-sm font-bold text-blue-700">{latestReport.pages_updated}</div>
              </div>
              <div className="p-2 bg-white/80 rounded-lg">
                <div className="text-gray-500">Không đổi:</div>
                <div className="text-sm font-bold text-gray-700">{latestReport.pages_unchanged}</div>
              </div>
              <div className="p-2 bg-white/80 rounded-lg">
                <div className="text-gray-500">Bỏ qua / Rỗng:</div>
                <div className="text-sm font-bold text-amber-700">{latestReport.pages_skipped}</div>
              </div>
              <div className="p-2 bg-white/80 rounded-lg">
                <div className="text-gray-500">Cursor mới:</div>
                <div className="text-sm font-bold text-purple-700">{latestReport.crawl_cursor}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Sync Execution History */}
      <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs overflow-hidden">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
              <Clock className="w-5 h-5 text-gray-500" />
              Lịch sử các lần chạy gần đây (Audit Sync Log)
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Theo dõi kết quả thực thi của cả các đợt chạy tự động (Scheduled) và thủ công (API/Manual).
            </p>
          </div>
          <span className="text-xs font-medium text-gray-500">
            {historyData.length} bản ghi gần nhất
          </span>
        </div>

        {historyData.length === 0 ? (
          <div className="p-8 text-center text-xs text-gray-400">
            Chưa có lịch sử đồng bộ nào được ghi nhận trong cơ sở dữ liệu.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-gray-50/80 border-b border-gray-100 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                  <th className="py-3 px-4">Thời gian hoàn tất</th>
                  <th className="py-3 px-3">Loại kích hoạt</th>
                  <th className="py-3 px-3">Trạng thái</th>
                  <th className="py-3 px-3 text-right">Thời lượng</th>
                  <th className="py-3 px-3 text-right">Mới</th>
                  <th className="py-3 px-3 text-right">Cập nhật</th>
                  <th className="py-3 px-3 text-right">Không đổi</th>
                  <th className="py-3 px-3 text-right">Bỏ qua</th>
                  <th className="py-3 px-3 text-right">Cursor</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {historyData.map((row, idx) => (
                  <tr key={idx} className="hover:bg-blue-50/30 transition-colors">
                    <td className="py-3 px-4 font-mono text-gray-700 whitespace-nowrap">
                      {row.completed_at ? row.completed_at.replace('T', ' ').slice(0, 19) : '—'}
                    </td>
                    <td className="py-3 px-3 whitespace-nowrap">
                      <span className="font-semibold text-gray-700 capitalize">
                        {row.trigger_type || 'scheduled'}
                      </span>
                    </td>
                    <td className="py-3 px-3 whitespace-nowrap">
                      {row.status === 'success' ? (
                        <Badge variant="success">Thành công</Badge>
                      ) : row.status === 'partial' ? (
                        <Badge variant="warning">Một phần</Badge>
                      ) : (
                        <Badge variant="danger">Lỗi</Badge>
                      )}
                    </td>
                    <td className="py-3 px-3 text-right font-mono text-gray-600">
                      {row.duration_seconds ? `${row.duration_seconds.toFixed(1)}s` : '—'}
                    </td>
                    <td className="py-3 px-3 text-right font-bold text-emerald-600 font-mono">
                      {row.pages_added ?? 0}
                    </td>
                    <td className="py-3 px-3 text-right font-bold text-blue-600 font-mono">
                      {row.pages_updated ?? 0}
                    </td>
                    <td className="py-3 px-3 text-right font-mono text-gray-600">
                      {row.pages_unchanged ?? 0}
                    </td>
                    <td className="py-3 px-3 text-right font-mono text-amber-600">
                      {row.pages_skipped ?? 0}
                    </td>
                    <td className="py-3 px-3 text-right font-mono text-purple-600">
                      {row.crawl_cursor ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
