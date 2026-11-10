import React, { useState } from 'react';
import {
  Settings,
  Shield,
  Key,
  Database,
  Lock,
  Unlock,
  CheckCircle,
  AlertTriangle,
  Server,
  Cloud,
  FileText,
  Info,
  Check
} from 'lucide-react';
import { Badge } from '../components/common/Badge';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';

export const SettingsPage: React.FC = () => {
  const { addToast } = useToast();
  const { token, saveToken, logout } = useAuth();
  const [tokenInput, setTokenInput] = useState(token);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isUnlocking, setIsUnlocking] = useState(false);

  const handleSaveToken = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tokenInput.trim()) {
      addToast({
        type: 'warning',
        title: 'Thiếu mã bảo mật',
        message: 'Vui lòng nhập Admin Token hợp lệ.'
      });
      return;
    }

    setIsVerifying(true);
    try {
      const valid = await saveToken(tokenInput.trim());
      if (valid) {
        addToast({
          type: 'success',
          title: 'Xác thực thành công!',
          message: 'Admin Token đã được xác thực và lưu trong phiên trình duyệt.'
        });
      } else {
        addToast({
          type: 'error',
          title: 'Token không hợp lệ',
          message: 'Không thể xác thực. Kiểm tra token và kết nối máy chủ.'
        });
      }
    } catch (err: any) {
      addToast({
        type: 'error',
        title: 'Lỗi kiểm tra token',
        message: err.message
      });
    } finally {
      setIsVerifying(false);
    }
  };

  const handleClearToken = () => {
    logout();
    setTokenInput('');
    addToast({
      type: 'info',
      title: 'Đã đăng xuất',
      message: 'Token quản trị đã được xóa khỏi phiên trình duyệt.'
    });
  };

  const handleForceUnlock = async () => {
    setIsUnlocking(true);
    try {
      const res = await api.unlockSync();
      addToast({
        type: 'success',
        title: 'Giải phóng khóa đồng bộ',
        message: res.message
      });
    } catch (err: any) {
      addToast({
        type: 'error',
        title: 'Lỗi giải phóng khóa',
        message: err.message
      });
    } finally {
      setIsUnlocking(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <Settings className="w-7 h-7 text-[#1463E8]" />
          Cài đặt & Bảo mật Hệ thống (System Settings)
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Quản lý khóa xác thực quản trị viên, thông tin môi trường máy chủ và kết nối XiaoZhi Cloud.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Admin Authentication Card */}
        <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs p-6 space-y-4">
          <div className="flex items-center gap-3 pb-3 border-b border-gray-100">
            <div className="w-10 h-10 rounded-xl bg-blue-50 text-[#1463E8] flex items-center justify-center">
              <Key className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-gray-900">Xác thực Quản trị viên (Admin Token)</h3>
              <p className="text-xs text-gray-500">Bảo vệ các thao tác nhạy cảm như Đồng bộ dữ liệu và Mở khóa hệ thống</p>
            </div>
          </div>

          <form onSubmit={handleSaveToken} className="space-y-3.5">
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">
                Admin Sync Token
              </label>
              <div className="relative">
                <input
                  type="password"
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Nhập mã bí mật ADMIN_SYNC_TOKEN..."
                  className="w-full px-3.5 py-2.5 text-xs font-mono bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:outline-hidden focus:border-[#1463E8] focus:ring-2 focus:ring-blue-100"
                />
              </div>
              <p className="text-[11px] text-gray-400 mt-1">
                Sử dụng token riêng do quản trị viên cấp từ cấu hình bảo mật của máy chủ.
              </p>
            </div>

            <div className="flex items-center gap-2 pt-2">
              <button
                type="submit"
                disabled={isVerifying}
                className="flex-1 py-2.5 text-xs font-bold text-white bg-[#1463E8] hover:bg-[#123B86] disabled:opacity-50 rounded-xl transition-all shadow-xs flex items-center justify-center gap-2"
              >
                {isVerifying ? 'Đang kiểm tra...' : 'Xác thực & Lưu Token'}
              </button>

              <button
                type="button"
                onClick={handleClearToken}
                className="px-3.5 py-2.5 text-xs font-semibold text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-xl transition-colors"
              >
                Đăng xuất
              </button>
            </div>
          </form>

          <div className="p-3 rounded-xl bg-blue-50/60 border border-blue-100 text-xs text-gray-700 space-y-1">
            <div className="font-bold text-[#123B86] flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-[#1463E8]" />
              Tiêu chuẩn an toàn:
            </div>
            <div>• Token chỉ được lưu trong phiên trình duyệt (Session Storage).</div>
            <div>• Không bao giờ gửi lộ token qua URL hoặc ghi vào file log công khai.</div>
          </div>
        </div>

        {/* SyncLock Concurrency Recovery Card */}
        <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs p-6 space-y-4">
          <div className="flex items-center gap-3 pb-3 border-b border-gray-100">
            <div className="w-10 h-10 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center">
              <Lock className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-gray-900">Quản lý Khóa Tiến trình (Concurrency Lock)</h3>
              <p className="text-xs text-gray-500">Khôi phục tiến trình khi xảy ra tình huống mất điện đột ngột hoặc dừng tiến trình</p>
            </div>
          </div>

          <div className="space-y-2 text-xs text-gray-600 leading-relaxed">
            <p>
              Hệ thống sử dụng cơ chế <strong>SyncLock</strong> kết hợp kiểm tra <strong>PID của hệ điều hành Windows</strong> để đảm bảo không có hai tiến trình đồng bộ nào chạy trùng lặp gây xung đột dữ liệu SQLite.
            </p>
            <p>
              Nếu tiến trình trước đó bị ngắt cưỡng bức và hệ thống báo lỗi <code>A synchronization job is already in progress</code>, bạn có thể thực hiện giải phóng khóa an toàn tại đây:
            </p>
          </div>

          <button
            onClick={handleForceUnlock}
            disabled={isUnlocking}
            className="w-full py-2.5 text-xs font-bold text-rose-700 bg-rose-50 border border-rose-200 hover:bg-rose-100 rounded-xl transition-colors flex items-center justify-center gap-2 shadow-2xs"
          >
            <Unlock className="w-4 h-4" />
            {isUnlocking ? 'Đang giải phóng...' : 'Giải phóng khóa đồng bộ (Force Unlock)'}
          </button>
        </div>

        {/* XiaoZhi Cloud Connection Info (Masked for Security) */}
        <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs p-6 space-y-4">
          <div className="flex items-center gap-3 pb-3 border-b border-gray-100">
            <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center">
              <Cloud className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-gray-900">Cấu hình XiaoZhi Cloud MCP</h3>
              <p className="text-xs text-gray-500">Bảo mật thông tin endpoint và JWT Token</p>
            </div>
          </div>

          <div className="space-y-3 text-xs">
            <div>
              <div className="text-gray-400 font-medium">XiaoZhi MCP WebSocket Endpoint:</div>
              <div className="font-mono text-gray-800 bg-gray-50 p-2 rounded-lg border border-gray-100 mt-1 truncate">
                Được quản lý trên máy chủ
              </div>
            </div>

            <div>
              <div className="text-gray-400 font-medium">XiaoZhi MCP JWT Token:</div>
              <div className="font-mono text-gray-800 bg-gray-50 p-2 rounded-lg border border-gray-100 mt-1 truncate">
                Không cung cấp qua API
              </div>
              <div className="text-[11px] text-emerald-600 font-medium mt-1 flex items-center gap-1">
                <Check className="w-3.5 h-3.5" />
                Token đã được che hoàn toàn nhằm bảo vệ an toàn thông tin
              </div>
            </div>
          </div>
        </div>

        {/* Server & Environment Information */}
        <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs p-6 space-y-4">
          <div className="flex items-center gap-3 pb-3 border-b border-gray-100">
            <div className="w-10 h-10 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center">
              <Server className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-gray-900">Môi trường Máy chủ (Server Blueprint)</h3>
              <p className="text-xs text-gray-500">Thông số kỹ thuật runtime và cấu trúc lưu trữ</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="p-2.5 rounded-xl bg-gray-50 border border-gray-100">
              <div className="text-gray-400">Hệ điều hành:</div>
              <div className="font-bold text-gray-800 mt-0.5">Windows 11 (x64)</div>
            </div>

            <div className="p-2.5 rounded-xl bg-gray-50 border border-gray-100">
              <div className="text-gray-400">Python Runtime:</div>
              <div className="font-bold text-gray-800 mt-0.5 font-mono">Python 3.14.4</div>
            </div>

            <div className="p-2.5 rounded-xl bg-gray-50 border border-gray-100">
              <div className="text-gray-400">Database Engine:</div>
              <div className="font-bold text-gray-800 mt-0.5">SQLite FTS5 Native</div>
            </div>

            <div className="p-2.5 rounded-xl bg-gray-50 border border-gray-100">
              <div className="text-gray-400">Cổng dịch vụ:</div>
              <div className="font-bold text-[#1463E8] mt-0.5 font-mono">Port 8000 (FastAPI)</div>
            </div>

            <div className="col-span-2 p-2.5 rounded-xl bg-gray-50 border border-gray-100">
              <div className="text-gray-400">Đường dẫn dữ liệu cục bộ:</div>
              <div className="font-mono text-gray-800 text-[11px] truncate mt-0.5">
                E:\WEWIN_IT\Wewin_AI_Connector\data\wewin_knowledge.db
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
