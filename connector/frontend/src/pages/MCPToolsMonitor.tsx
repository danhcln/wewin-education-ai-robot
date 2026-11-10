import React, { useState, useEffect } from 'react';
import {
  Wrench,
  Play,
  CheckCircle2,
  Code2,
  Terminal,
  Activity,
  Layers,
  Sparkles,
  RefreshCw,
  Search,
  BookOpen,
  Phone,
  Globe,
  Radio
} from 'lucide-react';
import { Badge } from '../components/common/Badge';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import { MCPToolDetail } from '../types';

export const MCPToolsMonitor: React.FC = () => {
  const { addToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [tools, setTools] = useState<MCPToolDetail[]>([]);
  const [selectedTool, setSelectedTool] = useState<string>('wewin_search');
  const [testArguments, setTestArguments] = useState<string>('{\n  "query": "IELTS",\n  "limit": 3\n}');
  const [isExecuting, setIsExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<any>(null);
  const [executionTime, setExecutionTime] = useState<number | null>(null);

  const fetchTools = async () => {
    setLoading(true);
    try {
      const res = await api.getMCPTools();
      setTools(res.tools || []);
    } catch (err: any) {
      addToast({
        type: 'error',
        title: 'Lỗi nạp danh sách công cụ MCP',
        message: err.message || 'Không thể liên lạc với backend API.'
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTools();
  }, []);

  const toolIconMap: Record<string, React.ReactNode> = {
    wewin_test_connection: <Radio className="w-5 h-5 text-emerald-600" />,
    wewin_search: <Search className="w-5 h-5 text-blue-600" />,
    wewin_get_programs: <BookOpen className="w-5 h-5 text-purple-600" />,
    wewin_get_contact: <Phone className="w-5 h-5 text-amber-600" />,
    wewin_get_page: <Globe className="w-5 h-5 text-cyan-600" />
  };

  const sampleArgsMap: Record<string, string> = {
    wewin_test_connection: '{}',
    wewin_search: '{\n  "query": "học phí luyện thi IELTS",\n  "limit": 3\n}',
    wewin_get_programs: '{\n  "category": "programs",\n  "limit": 5\n}',
    wewin_get_contact: '{}',
    wewin_get_page: '{\n  "url": "https://wewin.edu.vn/about/"\n}'
  };

  const handleSelectToolForTesting = (toolName: string) => {
    setSelectedTool(toolName);
    setTestArguments(sampleArgsMap[toolName] || '{}');
    setExecutionResult(null);
    setExecutionTime(null);
  };

  const handleExecuteTool = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsExecuting(true);
    const start = performance.now();

    try {
      let parsedArgs: Record<string, any> = {};
      try {
        parsedArgs = testArguments.trim() ? JSON.parse(testArguments) : {};
      } catch (parseErr) {
        addToast({
          type: 'error',
          title: 'JSON Arguments không hợp lệ',
          message: 'Vui lòng kiểm tra cú pháp JSON của tham số.'
        });
        setIsExecuting(false);
        return;
      }

      const res = await api.executeTool(selectedTool, parsedArgs);
      const elapsed = Math.round(performance.now() - start);
      setExecutionTime(elapsed);
      setExecutionResult(res);

      addToast({
        type: 'success',
        title: `Thực thi ${selectedTool} thành công`,
        message: `Hoàn tất trong ${elapsed}ms với dữ liệu thực từ SQLite.`
      });
    } catch (err: any) {
      setExecutionResult({ error: err.message });
      addToast({
        type: 'error',
        title: 'Lỗi thực thi công cụ MCP',
        message: err.message
      });
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Wrench className="w-7 h-7 text-[#1463E8]" />
            Giám sát Công cụ MCP (MCP Tools Monitor)
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Danh mục {tools.length} công cụ Model Context Protocol tại backend, chuẩn bị cho kết nối XiaoZhi Cloud và ESP32.
          </p>
        </div>

        <button
          onClick={fetchTools}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors shadow-xs"
        >
          <RefreshCw className={`w-4 h-4 text-gray-500 ${loading ? 'animate-spin' : ''}`} />
          Làm mới
        </button>
      </div>

      {/* Protocol Explanation Banner */}
      <div className="p-4.5 rounded-2xl bg-blue-50/70 border border-blue-200/80 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <Terminal className="w-5 h-5 text-[#1463E8] shrink-0 mt-0.5" />
          <div className="text-xs text-gray-700 leading-relaxed">
            <span className="font-bold text-[#123B86]">Cơ chế tương tác MCP:</span> Khi học viên hoặc phụ huynh hỏi ESP32 (ví dụ: "WeWIN có những khóa học nào?"), XiaoZhi Cloud gửi thông điệp JSON-RPC <code>tools/call</code> qua WebSocket Bridge. Backend thực thi truy vấn SQLite FTS5 và trả về thông tin xác thực để XiaoZhi tổng hợp giọng nói tiếng Việt.
          </div>
        </div>

        <div className="shrink-0 flex items-center gap-2 text-xs font-semibold text-emerald-700 bg-white px-3 py-1.5 rounded-lg border border-emerald-200 shadow-2xs">
          <CheckCircle2 className="w-4 h-4 text-emerald-600" />
          5/5 Công cụ Đăng ký Chuẩn MCP
        </div>
      </div>

      {/* 5 Registered Tools Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {tools.map((tool) => (
          <div
            key={tool.name}
            className={`p-5 rounded-2xl border transition-all duration-150 flex flex-col justify-between ${
              selectedTool === tool.name
                ? 'border-[#1463E8] bg-blue-50/20 shadow-md ring-2 ring-blue-100'
                : 'border-gray-200/90 bg-white shadow-xs hover:border-gray-300'
            }`}
          >
            <div>
              <div className="flex items-start justify-between gap-3 mb-2.5">
                <div className="flex items-center gap-2.5">
                  <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center">
                    {toolIconMap[tool.name] || <Wrench className="w-5 h-5 text-gray-600" />}
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-gray-900 font-mono">{tool.name}</h3>
                    <Badge variant="success">MCP Active</Badge>
                  </div>
                </div>
              </div>

              <p className="text-xs text-gray-600 leading-relaxed min-h-[40px]">
                {tool.description}
              </p>

              {/* Input Schema Parameters */}
              <div className="mt-3 pt-3 border-t border-gray-100">
                <div className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mb-1.5">
                  Tham số đầu vào (Input Schema):
                </div>
                {tool.inputSchema?.properties && Object.keys(tool.inputSchema.properties).length > 0 ? (
                  <div className="space-y-1">
                    {Object.entries(tool.inputSchema.properties).map(([key, prop]: [string, any]) => (
                      <div key={key} className="flex items-center justify-between text-xs font-mono bg-gray-50 px-2.5 py-1 rounded-md">
                        <span className="font-semibold text-gray-800">{key}</span>
                        <span className="text-[11px] text-gray-500">
                          {prop.type} {tool.inputSchema?.required?.includes(key) ? '(Bắt buộc)' : '(Tùy chọn)'}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-gray-400 italic">Không yêu cầu tham số</div>
                )}
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between">
              <span className="text-[11px] text-gray-400">JSON-RPC 2.0</span>
              <button
                onClick={() => handleSelectToolForTesting(tool.name)}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors flex items-center gap-1.5 ${
                  selectedTool === tool.name
                    ? 'bg-[#1463E8] text-white'
                    : 'bg-gray-100 hover:bg-gray-200 text-gray-700'
                }`}
              >
                <Play className="w-3 h-3 fill-current" />
                Kiểm thử công cụ
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Interactive Tool Sandbox Tester */}
      <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs p-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-5 border-b border-gray-100">
          <div>
            <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
              <Code2 className="w-5 h-5 text-[#1463E8]" />
              Hộp kiểm thử tương tác MCP (Interactive Live Tool Tester)
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Gửi yêu cầu thực thi trực tiếp đến backend và quan sát cấu trúc dữ liệu trả về giống như khi XiaoZhi Cloud gọi công cụ.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Đang chọn:</span>
            <span className="px-2.5 py-1 bg-blue-50 border border-blue-200 rounded-lg text-xs font-mono font-bold text-blue-700">
              {selectedTool}
            </span>
          </div>
        </div>

        <form onSubmit={handleExecuteTool} className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-5">
          {/* Left: Input parameters */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-bold text-gray-700">
                Tham số JSON đầu vào (JSON Arguments):
              </label>
              <button
                type="button"
                onClick={() => setTestArguments(sampleArgsMap[selectedTool] || '{}')}
                className="text-xs text-[#1463E8] hover:underline font-medium"
              >
                Khôi phục mẫu
              </button>
            </div>

            <textarea
              rows={8}
              value={testArguments}
              onChange={(e) => setTestArguments(e.target.value)}
              className="w-full p-3 font-mono text-xs bg-gray-900 text-emerald-400 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-blue-500 resize-y leading-relaxed"
              placeholder="{}"
            />

            <button
              type="submit"
              disabled={isExecuting}
              className="w-full py-2.5 text-xs font-bold text-white bg-[#1463E8] hover:bg-[#123B86] disabled:opacity-50 rounded-xl transition-all shadow-xs flex items-center justify-center gap-2 active:scale-98"
            >
              {isExecuting ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Đang thực thi công cụ trên máy chủ...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  Thực thi công cụ ngay (Execute Tool)
                </>
              )}
            </button>
          </div>

          {/* Right: Output response */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-gray-700">
                Kết quả trả về từ Backend (Live MCP Response):
              </span>
              {executionTime !== null && (
                <span className="text-[11px] font-mono text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md font-semibold">
                  Thời gian: {executionTime}ms
                </span>
              )}
            </div>

            <div className="h-60 overflow-auto bg-gray-950 p-3 rounded-xl border border-gray-800">
              {executionResult ? (
                <pre className="font-mono text-xs text-blue-300 whitespace-pre-wrap">
                  {JSON.stringify(executionResult, null, 2)}
                </pre>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-gray-500 text-xs">
                  <Terminal className="w-8 h-8 text-gray-600 mb-2" />
                  <span>Chưa có kết quả thực thi.</span>
                  <span>Bấm "Thực thi công cụ ngay" để kiểm tra.</span>
                </div>
              )}
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
