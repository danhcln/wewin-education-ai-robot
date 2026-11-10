import React, { useState } from 'react';
import { Badge } from '../components/common/Badge';
import {
  Bot,
  Cpu,
  Wrench,
  Database,
  ExternalLink,
  Sliders,
  History,
  CheckCircle2,
  Volume2,
  Sparkles,
  Info,
  X
} from 'lucide-react';

export const AIAssistants: React.FC = () => {
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false);
  const [isHistoryModalOpen, setIsHistoryModalOpen] = useState(false);

  const assistant = {
    id: 'asst-vi-01',
    name: 'AI Vietnamese',
    role: 'Trợ lý tiếng Việt thông minh cho học sinh & phụ huynh WeWIN',
    voiceRole: 'Unknown — chưa xác minh Cloud',
    model: 'Unknown',
    status: 'unknown',
    lastConversation: 'Unknown — chưa có lịch sử thiết bị',
    device: {
      name: 'ESP32-S3 N16R8',
      type: 'Smart Audio Assistant',
      ip: 'Unknown',
      firmware: 'Unknown'
    },
    knowledgeSource: 'WeWIN Website RAG & Curated Seeds (SQLite FTS5)',
    tools: [
      { name: 'wewin_search', desc: 'Tìm kiếm tri thức khóa học, tài liệu, học phí' },
      { name: 'wewin_get_programs', desc: 'Đề xuất chương trình theo độ tuổi (Mầm non, Cambridge, IELTS)' },
      { name: 'wewin_get_contact', desc: 'Hotline, Zalo và 2 cơ sở Bình Thạnh' },
      { name: 'wewin_get_page', desc: 'Đọc chi tiết toàn văn bài viết' },
      { name: 'wewin_test_connection', desc: 'Kiểm tra đường truyền MCP Ping' }
    ]
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-white p-5 rounded-2xl border border-slate-200/80 shadow-xs">
        <div>
          <h2 className="text-base font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <Bot className="w-5 h-5 text-blue-600" />
            <span>Trợ Lý AI (1 trợ lý đã đăng ký)</span>
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Quản lý các Agent AI được kết nối với hệ thống WeWIN qua giao thức XiaoZhi Cloud MCP
          </p>
        </div>

        <div className="flex items-center gap-2">
          <a
            href="https://xiaozhi.me"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white shadow-sm transition-all"
          >
            <span>Mở Bảng Điều Khiển XiaoZhi</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>

      {/* Main Assistant Card (Styled after Reference Image 1 with WeWIN Branding) */}
      <div className="bg-white rounded-3xl p-6 sm:p-7 border border-slate-200/90 shadow-sm hover:shadow-md transition-all">
        {/* Top Header of Card */}
        <div className="flex items-start justify-between gap-4 pb-6 border-b border-slate-100">
          <div className="flex items-center gap-4">
            {/* Official WeWIN AI Avatar */}
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[#123B86] to-[#1463E8] p-2.5 flex items-center justify-center shrink-0 shadow-md shadow-blue-500/15 relative">
              <img
                src="/wewin_icon.png"
                alt="WeWIN AI Assistant"
                className="w-full h-full object-contain drop-shadow"
              />
              <span className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-emerald-500 border-2 border-white animate-pulse-glow" />
            </div>

            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-xl font-bold text-slate-900">{assistant.name}</h3>
                <Badge variant="success" size="sm">Đang hoạt động</Badge>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded-md bg-slate-100 text-slate-600">ID: {assistant.id}</span>
              </div>
              <p className="text-xs text-slate-500 mt-1 max-w-xl">
                {assistant.role}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-emerald-600 font-medium hidden sm:inline-flex items-center gap-1.5 bg-emerald-50 px-3 py-1.5 rounded-full border border-emerald-100">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
              <span>Xác thực MCP Bridge</span>
            </span>
          </div>
        </div>

        {/* Metadata Details Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 py-5 border-b border-slate-100 text-xs">
          <div className="p-3.5 rounded-xl bg-slate-50/70 border border-slate-100">
            <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5 mb-1">
              <Volume2 className="w-3.5 h-3.5 text-slate-500" />
              <span>Vai trò / Giọng đọc</span>
            </div>
            <div className="font-semibold text-slate-800">{assistant.voiceRole}</div>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-50/70 border border-slate-100">
            <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5 mb-1">
              <Sparkles className="w-3.5 h-3.5 text-amber-500" />
              <span>Mô hình AI</span>
            </div>
            <div className="font-semibold text-slate-800">{assistant.model}</div>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-50/70 border border-slate-100">
            <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5 mb-1">
              <History className="w-3.5 h-3.5 text-blue-500" />
              <span>Tương tác gần nhất</span>
            </div>
            <div className="font-semibold text-slate-800">{assistant.lastConversation}</div>
          </div>
        </div>

        {/* Data Source & Linked Device */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 py-5 border-b border-slate-100 text-xs">
          <div>
            <div className="font-semibold text-slate-700 mb-2 flex items-center gap-2">
              <Database className="w-4 h-4 text-blue-600" />
              <span>Nguồn tri thức được kết nối</span>
            </div>
            <div className="p-3 rounded-xl bg-blue-50/50 border border-blue-100 text-slate-600 text-xs leading-relaxed">
              Trợ lý được cấp quyền truy cập thời gian thực vào cơ sở dữ liệu SQLite FTS5 của WeWIN. Khi học sinh đặt câu hỏi, AI tự động kích hoạt MCP Tools để trích xuất khóa học, học bổng và hotline chính xác.
            </div>
          </div>

          <div>
            <div className="font-semibold text-slate-700 mb-2 flex items-center gap-2">
              <Cpu className="w-4 h-4 text-indigo-600" />
              <span>Thiết bị phần cứng liên kết</span>
            </div>
            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/80 flex items-center justify-between">
              <div>
                <div className="font-bold text-slate-800">{assistant.device.name}</div>
                <div className="text-[11px] text-slate-500">{assistant.device.type} &bull; {assistant.device.firmware}</div>
              </div>
              <Badge variant="success" size="sm">Unknown</Badge>
            </div>
          </div>
        </div>

        {/* Enabled MCP Tools List */}
        <div className="py-5 border-b border-slate-100">
          <div className="font-semibold text-xs text-slate-700 mb-3 flex items-center gap-2">
            <Wrench className="w-4 h-4 text-blue-600" />
            <span>5 Công cụ MCP được kích hoạt tự động cho trợ lý</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
            {assistant.tools.map((t) => (
              <div key={t.name} className="p-3 rounded-xl border border-slate-200/70 bg-white shadow-2xs">
                <div className="font-mono text-xs font-bold text-blue-700">{t.name}</div>
                <div className="text-[11px] text-slate-500 mt-1">{t.desc}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Action Buttons Toolbar */}
        <div className="pt-5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsConfigModalOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors"
            >
              <Sliders className="w-4 h-4 text-slate-500" />
              <span>Cấu hình Agent</span>
            </button>

            <button
              onClick={() => setIsHistoryModalOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors"
            >
              <History className="w-4 h-4 text-slate-500" />
              <span>Lịch sử hội thoại</span>
            </button>
          </div>

          <a
            href="https://xiaozhi.me"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-blue-600 hover:text-blue-700 font-semibold inline-flex items-center gap-1.5"
          >
            <span>Quản lý chi tiết trên XiaoZhi Cloud</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>

      {/* Configuration Modal */}
      {isConfigModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 border border-slate-200 shadow-2xl relative">
            <button
              onClick={() => setIsConfigModalOpen(false)}
              className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-slate-600"
            >
              <X className="w-5 h-5" />
            </button>
            <h3 className="text-base font-bold text-slate-900 mb-2">Thông Tin Cấu Hình Agent AI Vietnamese</h3>
            <p className="text-xs text-slate-500 mb-4">
              Cấu hình được quản lý trên nền tảng XiaoZhi Cloud và kết nối với WeWIN AI Connector thông qua MCP WebSocket.
            </p>

            <div className="space-y-3 text-xs bg-slate-50 p-4 rounded-xl border border-slate-100 font-mono">
              <div><strong className="text-slate-700">Agent Name:</strong> AI Vietnamese</div>
              <div><strong className="text-slate-700">Endpoint ID:</strong> Unknown</div>
              <div><strong className="text-slate-700">MCP Protocol:</strong> JSON-RPC 2.0 (WebSocket)</div>
              <div><strong className="text-slate-700">Model Engine:</strong> Unknown — chưa xác minh Cloud</div>
              <div><strong className="text-slate-700">System Prompt:</strong> Trợ lý AI tiếng Việt của Hệ thống Anh ngữ WeWIN Education</div>
            </div>

            <div className="mt-5 flex justify-end">
              <button
                onClick={() => setIsConfigModalOpen(false)}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

      {/* History Modal */}
      {isHistoryModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 border border-slate-200 shadow-2xl relative">
            <button
              onClick={() => setIsHistoryModalOpen(false)}
              className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-slate-600"
            >
              <X className="w-5 h-5" />
            </button>
            <h3 className="text-base font-bold text-slate-900 mb-2">Nhật Ký Tương Tác Giọng Nói Gần Nhất</h3>
            <p className="text-xs text-slate-500 mb-4">
              Các phiên hỏi đáp mẫu từ robot ESP32-S3 đã hoàn tất trong benchmark:
            </p>

            <div className="space-y-3 text-xs">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-100">
                <div className="font-semibold text-slate-800">Q: "WeWIN Education là gì?"</div>
                <div className="text-slate-600 mt-1">A: Giới thiệu hệ thống đào tạo Anh ngữ thuộc Ngoại ngữ Công Thành tại TP.HCM.</div>
              </div>
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-100">
                <div className="font-semibold text-slate-800">Q: "Con tôi 9 tuổi thì có chương trình nào?"</div>
                <div className="text-slate-600 mt-1">A: Gợi ý Tiếng Anh Cambridge (Tiểu học) Movers/Flyers kèm 1 buổi test 4 kỹ năng miễn phí.</div>
              </div>
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-100">
                <div className="font-semibold text-slate-800">Q: "Hotline WeWIN là bao nhiêu?"</div>
                <div className="text-slate-600 mt-1">A: 034 596 9388 - 037 866 9388 (CS1 & CS2 Bình Thạnh).</div>
              </div>
            </div>

            <div className="mt-5 flex justify-end">
              <button
                onClick={() => setIsHistoryModalOpen(false)}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
