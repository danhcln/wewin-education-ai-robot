import {PhysicalEnrollmentPanel} from '../media/PhysicalEnrollmentPanel';
import React, { useState } from 'react';
import {
  Cpu,
  Mic,
  Volume2,
  Tv,
  Wifi,
  Activity,
  Plus,
  RefreshCw,
  ExternalLink,
  Bot,
  Zap,
  MapPin,
  Sparkles,
  Info
} from 'lucide-react';
import { Badge } from '../components/common/Badge';
import { useToast } from '../context/ToastContext';

export const RobotManagement: React.FC = () => {
  const { addToast } = useToast();
  const [isPinging, setIsPinging] = useState(false);
  const [lastPingResult, setLastPingResult] = useState<{ status: string; latency: number } | null>(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newDeviceName, setNewDeviceName] = useState('');
  const [newDeviceBranch, setNewDeviceBranch] = useState('WeWIN Cơ sở 1');

  const handlePingHealth = async () => {
    setIsPinging(true);
    const start = performance.now();
    try {
      const res = await fetch('/health');
      const data = await res.json();
      const latency = Math.round(performance.now() - start);
      if (res.ok && data.status === 'healthy') {
        setLastPingResult({ status: 'Backend Healthy', latency });
        addToast({
          type: 'success',
          title: 'Kết nối Backend ổn định',
          message: `Phản hồi trong ${latency}ms. SQLite Database: ${data.database_ok ? 'Kết nối tốt' : 'Cảnh báo'}.`
        });
      } else {
        setLastPingResult({ status: 'Cảnh báo', latency });
        addToast({
          type: 'warning',
          title: 'Phản hồi bất thường',
          message: `Trạng thái: ${JSON.stringify(data)}`
        });
      }
    } catch (err: any) {
      setLastPingResult({ status: 'Mất kết nối', latency: 0 });
      addToast({
        type: 'error',
        title: 'Lỗi kiểm tra Backend',
        message: err.message || 'Không thể liên lạc với máy chủ FastAPI.'
      });
    } finally {
      setIsPinging(false);
    }
  };

  const handleRegisterDevice = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDeviceName.trim()) {
      addToast({ type: 'warning', title: 'Thiếu thông tin', message: 'Vui lòng nhập tên thiết bị.' });
      return;
    }
    addToast({
      type: 'info',
      title: 'Chưa đăng ký thiết bị',
      message: `Thiết bị "${newDeviceName}" thuộc "${newDeviceBranch}" chưa được lưu; chức năng đăng ký thiết bị chưa được triển khai.`
    });
    setIsAddModalOpen(false);
    setNewDeviceName('');
  };

  return (
    <div className="space-y-6">
      <PhysicalEnrollmentPanel/>
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Bot className="w-7 h-7 text-[#1463E8]" />
            Quản lý Thiết bị / Robot
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Quản lý phần cứng trợ lý AI ESP32-S3 N16R8 và hạ tầng robot tại các cơ sở WeWIN Education.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handlePingHealth}
            disabled={isPinging}
            className="inline-flex items-center gap-2 px-3.5 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 hover:border-gray-300 transition-all shadow-xs"
          >
            <RefreshCw className={`w-4 h-4 text-gray-500 ${isPinging ? 'animate-spin' : ''}`} />
            Kiểm tra Backend
          </button>
          <button
            onClick={() => setIsAddModalOpen(true)}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-[#1463E8] rounded-xl hover:bg-[#123B86] transition-all shadow-sm shadow-blue-500/20 active:scale-95"
          >
            <Plus className="w-4 h-4" />
            Thêm thiết bị mới
          </button>
        </div>
      </div>

      {/* Top Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-4.5 rounded-2xl border border-gray-100 shadow-xs flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center text-[#1463E8]">
            <Bot className="w-6 h-6" />
          </div>
          <div>
            <div className="text-xs font-medium text-gray-500">Robot dự kiến</div>
            <div className="text-xl font-bold text-gray-900 mt-0.5">Chưa xác minh</div>
            <div className="text-xs text-emerald-600 font-medium flex items-center gap-1 mt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
              Chưa xác minh kết nối robot
            </div>
          </div>
        </div>

        <div className="bg-white p-4.5 rounded-2xl border border-gray-100 shadow-xs flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-purple-50 flex items-center justify-center text-purple-600">
            <Cpu className="w-6 h-6" />
          </div>
          <div>
            <div className="text-xs font-medium text-gray-500">Vi điều khiển</div>
            <div className="text-xl font-bold text-gray-900 mt-0.5">ESP32-S3</div>
            <div className="text-xs text-gray-500 font-medium mt-0.5">N16R8 (16MB/8MB)</div>
          </div>
        </div>

        <div className="bg-white p-4.5 rounded-2xl border border-gray-100 shadow-xs flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-amber-50 flex items-center justify-center text-amber-600">
            <Zap className="w-6 h-6" />
          </div>
          <div>
            <div className="text-xs font-medium text-gray-500">Xử lý âm thanh</div>
            <div className="text-xl font-bold text-gray-900 mt-0.5">I2S Opus</div>
            <div className="text-xs text-gray-500 font-medium mt-0.5">INMP441 & MAX98357A</div>
          </div>
        </div>

        <div className="bg-white p-4.5 rounded-2xl border border-gray-100 shadow-xs flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-emerald-50 flex items-center justify-center text-emerald-600">
            <Activity className="w-6 h-6" />
          </div>
          <div>
            <div className="text-xs font-medium text-gray-500">Kiểm tra Backend</div>
            <div className="text-xl font-bold text-gray-900 mt-0.5">
              {lastPingResult ? lastPingResult.status : 'Unknown'}
            </div>
            <div className="text-xs text-gray-500 font-medium mt-0.5">
              {lastPingResult ? `${lastPingResult.latency}ms phản hồi` : 'Bấm "Kiểm tra Backend"'}
            </div>
          </div>
        </div>
      </div>

      {/* Primary Hardware Unit Card */}
      <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs overflow-hidden">
        {/* Card Header */}
        <div className="p-6 border-b border-gray-100 flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-gradient-to-r from-blue-50/50 via-white to-amber-50/20">
          <div className="flex items-start gap-4">
            <div className="relative">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-[#123B86] to-[#1463E8] flex items-center justify-center text-white shadow-md shadow-blue-500/20">
                <Bot className="w-7 h-7" />
              </div>
              <span className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-slate-400 border-2 border-white flex items-center justify-center">
                <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse"></span>
              </span>
            </div>

            <div>
              <div className="flex items-center gap-2.5">
                <h3 className="text-lg font-bold text-gray-900">WeWIN AI Smart Robot #1</h3>
                <Badge variant="gray">Unknown</Badge>
                <Badge variant="blue">Cơ sở chính</Badge>
              </div>
              <p className="text-xs text-gray-500 mt-1 flex items-center gap-2">
                <span>Model: <strong>ESP32-S3-N16R8-Wewin01</strong></span>
                <span>•</span>
                <span>Firmware: <strong>Unknown</strong></span>
                <span>•</span>
                <span className="text-slate-500 font-medium">Unknown — chưa có heartbeat</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <a
              href="https://xiaozhi.me/"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5 text-gray-500" />
              Trang cấu hình XiaoZhi
            </a>
          </div>
        </div>

        {/* Technical Hardware Specs Breakdown */}
        <div className="p-6">
          <h4 className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-4">
            Cấu hình phần cứng chi tiết (Hardware Blueprint)
          </h4>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Spec 1: SoC */}
            <div className="p-4 rounded-xl border border-gray-100 bg-[#F7FAFF]/80 hover:border-blue-200 transition-colors">
              <div className="flex items-center gap-2.5 text-[#1463E8] mb-2">
                <Cpu className="w-5 h-5" />
                <span className="text-xs font-bold uppercase tracking-wider text-gray-700">Vi điều khiển chính</span>
              </div>
              <div className="text-sm font-bold text-gray-900">ESP32-S3 N16R8</div>
              <div className="text-xs text-gray-500 mt-1 space-y-0.5">
                <div>• Xtensa Dual-Core 240MHz</div>
                <div>• 16MB SPI Flash</div>
                <div>• 8MB Octal PSRAM</div>
              </div>
            </div>

            {/* Spec 2: Microphone */}
            <div className="p-4 rounded-xl border border-gray-100 bg-[#F7FAFF]/80 hover:border-blue-200 transition-colors">
              <div className="flex items-center gap-2.5 text-blue-600 mb-2">
                <Mic className="w-5 h-5" />
                <span className="text-xs font-bold uppercase tracking-wider text-gray-700">Thu âm (Audio In)</span>
              </div>
              <div className="text-sm font-bold text-gray-900">INMP441 MEMS Mic</div>
              <div className="text-xs text-gray-500 mt-1 space-y-0.5">
                <div>• Giao tiếp I2S Digital</div>
                <div>• Omnidirectional 24-bit</div>
                <div>• Khử ồn giọng nói định hướng</div>
              </div>
            </div>

            {/* Spec 3: Speaker */}
            <div className="p-4 rounded-xl border border-gray-100 bg-[#F7FAFF]/80 hover:border-blue-200 transition-colors">
              <div className="flex items-center gap-2.5 text-amber-600 mb-2">
                <Volume2 className="w-5 h-5" />
                <span className="text-xs font-bold uppercase tracking-wider text-gray-700">Phát âm (Audio Out)</span>
              </div>
              <div className="text-sm font-bold text-gray-900">MAX98357A I2S DAC</div>
              <div className="text-xs text-gray-500 mt-1 space-y-0.5">
                <div>• Khuếch đại Class-D 3W</div>
                <div>• Loa dải rộng 4Ω 3W</div>
                <div>• Lấy mẫu âm thanh chuẩn XiaoZhi</div>
              </div>
            </div>

            {/* Spec 4: Display */}
            <div className="p-4 rounded-xl border border-gray-100 bg-[#F7FAFF]/80 hover:border-blue-200 transition-colors">
              <div className="flex items-center gap-2.5 text-purple-600 mb-2">
                <Tv className="w-5 h-5" />
                <span className="text-xs font-bold uppercase tracking-wider text-gray-700">Màn hình OLED</span>
              </div>
              <div className="text-sm font-bold text-gray-900">SSD1306 0.96&quot;</div>
              <div className="text-xs text-gray-500 mt-1 space-y-0.5">
                <div>• Độ phân giải 128×64 px</div>
                <div>• Giao thức I2C (SCL/SDA)</div>
                <div>• Biểu cảm mắt & sóng âm thanh</div>
              </div>
            </div>
          </div>

          {/* System Network & Protocol Status */}
          <div className="mt-5 p-4 rounded-xl bg-blue-50/50 border border-blue-100/80 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <Wifi className="w-5 h-5 text-[#1463E8] shrink-0 mt-0.5" />
              <div>
                <div className="text-xs font-bold text-[#123B86]">Giao thức kết nối & Truyền thông thời gian thực</div>
                <div className="text-xs text-gray-600 mt-0.5 leading-relaxed">
                  Robot kết nối Wi-Fi 2.4GHz truyền trực tiếp luồng giọng nói đến XiaoZhi Cloud qua giao thức WebSocket Opus.
                  Khi người dùng hỏi về WeWIN, XiaoZhi Cloud gọi các công cụ MCP trên máy chủ này qua <strong>MCP WebSocket Bridge</strong>.
                </div>
              </div>
            </div>

            <div className="shrink-0 flex items-center gap-2 text-xs font-semibold text-emerald-700 bg-white px-3 py-1.5 rounded-lg border border-emerald-200 shadow-2xs">
              <span className="w-2 h-2 rounded-full bg-slate-400 animate-pulse"></span>
              Bridge MCP: Unknown
            </div>
          </div>
        </div>

        {/* Hardware Status Note */}
        <div className="px-6 py-3.5 bg-gray-50 border-t border-gray-100 flex items-center gap-2 text-xs text-gray-500">
          <Info className="w-4 h-4 text-blue-500 shrink-0" />
          <span>
            Trạng thái pin, cường độ Wi-Fi RSSI và độ ẩm phần cứng do firmware XiaoZhi quản lý trực tiếp qua đám mây. Dashboard chỉ hiển thị thông tin thực tế được xác minh từ backend.
          </span>
        </div>
      </div>

      {/* Multi-Robot Campus Fleet Preview */}
      <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-amber-500" />
              Kế hoạch Mở rộng Hệ thống Robot (Campus Fleet Expansion)
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Hệ thống được thiết kế sẵn sàng mở rộng để quản lý đồng thời nhiều robot trợ lý tại các chi nhánh WeWIN Education.
            </p>
          </div>
          <span className="text-xs font-semibold text-[#1463E8] bg-blue-50 px-2.5 py-1 rounded-full">
            Đa cơ sở / Multi-Tenant Ready
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 rounded-xl border-2 border-blue-500/20 bg-blue-50/20 relative">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold text-blue-700 flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5" />
                Cơ sở 1 – Quầy Tiếp tân
              </span>
              <Badge variant="gray">Unknown</Badge>
            </div>
            <div className="text-sm font-bold text-gray-900">ESP32-S3 Robot Alpha</div>
            <p className="text-xs text-gray-500 mt-1">Phục vụ giải đáp phụ huynh và học viên đến tham quan trung tâm.</p>
          </div>

          <div className="p-4 rounded-xl border border-dashed border-gray-300 bg-gray-50/50 relative hover:border-gray-400 transition-colors">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold text-gray-500 flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5" />
                Cơ sở 2 – Phòng Luyện IELTS
              </span>
              <Badge variant="gray">Chờ ghép nối</Badge>
            </div>
            <div className="text-sm font-bold text-gray-700">ESP32-S3 Robot Beta</div>
            <p className="text-xs text-gray-400 mt-1">Hỗ trợ học viên tra cứu đề thi, lịch thi thử và mẹo làm bài IELTS.</p>
          </div>

          <div className="p-4 rounded-xl border border-dashed border-gray-300 bg-gray-50/50 relative hover:border-gray-400 transition-colors">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold text-gray-500 flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5" />
                Cơ sở 3 – Khu Vực Trẻ Em (Kids)
              </span>
              <Badge variant="gray">Chờ ghép nối</Badge>
            </div>
            <div className="text-sm font-bold text-gray-700">ESP32-S3 Robot Gamma</div>
            <p className="text-xs text-gray-400 mt-1">Tương tác tiếng Anh giao tiếp và kể chuyện cho học viên nhí.</p>
          </div>
        </div>
      </div>

      {/* Add Device Modal */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/40 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-md w-full shadow-2xl border border-gray-100 overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="p-5 border-b border-gray-100 flex items-center justify-between bg-gradient-to-r from-blue-50/60 to-white">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-blue-100 text-[#1463E8] flex items-center justify-center">
                  <Bot className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-gray-900">Đăng ký Robot mới</h3>
                  <p className="text-xs text-gray-500">Mở rộng thêm robot ESP32-S3 vào hệ thống</p>
                </div>
              </div>
              <button
                onClick={() => setIsAddModalOpen(false)}
                className="text-gray-400 hover:text-gray-600 text-lg leading-none p-1"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleRegisterDevice} className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Tên thiết bị / Robot
                </label>
                <input
                  type="text"
                  required
                  placeholder="Ví dụ: WeWIN AI Robot Cơ sở 2"
                  value={newDeviceName}
                  onChange={(e) => setNewDeviceName(e.target.value)}
                  className="w-full px-3.5 py-2 text-sm border border-gray-200 rounded-xl focus:outline-hidden focus:border-[#1463E8] focus:ring-2 focus:ring-blue-100"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Vị trí cơ sở triển khai
                </label>
                <select
                  value={newDeviceBranch}
                  onChange={(e) => setNewDeviceBranch(e.target.value)}
                  className="w-full px-3.5 py-2 text-sm border border-gray-200 rounded-xl focus:outline-hidden focus:border-[#1463E8] focus:ring-2 focus:ring-blue-100 bg-white"
                >
                  <option value="WeWIN Cơ sở 1 - Trụ sở chính">WeWIN Cơ sở 1 - Trụ sở chính</option>
                  <option value="WeWIN Cơ sở 2 - Trung tâm IELTS">WeWIN Cơ sở 2 - Trung tâm IELTS</option>
                  <option value="WeWIN Cơ sở 3 - Tiếng Anh Trẻ Em">WeWIN Cơ sở 3 - Tiếng Anh Trẻ Em</option>
                </select>
              </div>

              <div className="p-3 rounded-xl bg-amber-50 border border-amber-200/70 text-xs text-amber-800 space-y-1">
                <div className="font-bold flex items-center gap-1.5">
                  <Info className="w-3.5 h-3.5" />
                  Quy trình ghép nối XiaoZhi:
                </div>
                <div>1. Xác minh phiên bản firmware hiện có trước khi ghép thiết bị.</div>
                <div>2. Dùng điện thoại kết nối AP Wi-Fi của ESP32 để nhập Wi-Fi trường học.</div>
                <div>3. Quét mã QR trên OLED để gán robot vào trợ lý AI Vietnamese.</div>
              </div>

              <div className="flex items-center justify-end gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="px-4 py-2 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded-xl transition-colors"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 text-xs font-semibold text-white bg-[#1463E8] hover:bg-[#123B86] rounded-xl transition-all shadow-xs"
                >
                  Lưu & Đăng ký
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
