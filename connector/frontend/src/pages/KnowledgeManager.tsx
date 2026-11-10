import React, { useState, useEffect } from 'react';
import {
  Database,
  Search,
  ExternalLink,
  Eye,
  FileText,
  Filter,
  CheckCircle,
  Clock,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  Copy,
  Hash,
  X
} from 'lucide-react';
import { Badge } from '../components/common/Badge';
import { EmptyState } from '../components/common/EmptyState';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { KnowledgeItem, KnowledgeResponse } from '../types';

export const KnowledgeManager: React.FC = () => {
  const { addToast } = useToast();
  const { isAuthenticated } = useAuth();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<KnowledgeResponse | null>(null);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [sourceType, setSourceType] = useState('all');
  const [page, setPage] = useState(1);
  const [selectedItem, setSelectedItem] = useState<KnowledgeItem | null>(null);

  const fetchPages = async () => {
    if (!isAuthenticated) {
      setData(null);
      setSelectedItem(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await api.getKnowledgePages({
        page,
        limit: 12,
        search: search.trim() || undefined,
        category: category !== 'all' ? category : undefined,
        source_type: sourceType !== 'all' ? sourceType : undefined
      });
      setData(res);
    } catch (err: any) {
      addToast({
        type: 'error',
        title: 'Lỗi tải cơ sở kiến thức',
        message: err.message || 'Không thể lấy danh sách trang từ SQLite.'
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPages();
  }, [page, category, sourceType, isAuthenticated]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchPages();
  };

  const handleCopyContent = (text: string) => {
    navigator.clipboard.writeText(text);
    addToast({
      type: 'success',
      title: 'Đã sao chép nội dung',
      message: 'Nội dung bài viết đã được lưu vào clipboard.'
    });
  };

  const categories = [
    { id: 'all', label: 'Tất cả danh mục' },
    { id: 'programs', label: 'Chương trình đào tạo' },
    { id: 'ielts', label: 'Khóa học IELTS' },
    { id: 'kids', label: 'Tiếng Anh trẻ em' },
    { id: 'contact', label: 'Liên hệ & Tuyển sinh' },
    { id: 'about', label: 'Giới thiệu WeWIN' },
    { id: 'placement-test', label: 'Thi xếp lớp' }
  ];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Database className="w-7 h-7 text-[#1463E8]" />
            Kho kiến thức WeWIN (SQLite FTS5)
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Toàn bộ nội dung chính thức từ wewin.edu.vn được lập chỉ mục toàn văn (Full-Text Search FTS5) phục vụ trợ lý AI.
          </p>
        </div>

        {data && (
          <div className="flex items-center gap-2.5">
            <span className="px-3.5 py-1.5 text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-200/60 rounded-xl">
              Tổng số trang: <strong>{data.total}</strong>
            </span>
            <span className="px-3.5 py-1.5 text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200/60 rounded-xl">
              Trang hiện tại: <strong>{data.page} / {data.total_pages || 1}</strong>
            </span>
          </div>
        )}
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-white p-4 rounded-2xl border border-gray-200/90 shadow-xs space-y-3.5">
        <form onSubmit={handleSearchSubmit} className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Tìm kiếm theo từ khóa trong tiêu đề hoặc nội dung (VD: IELTS, học phí, địa chỉ, lịch học)..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 text-sm bg-gray-50/70 border border-gray-200 rounded-xl focus:bg-white focus:outline-hidden focus:border-[#1463E8] focus:ring-2 focus:ring-blue-100 transition-all"
            />
          </div>

          <div className="flex items-center gap-2">
            <select
              value={sourceType}
              onChange={(e) => {
                setSourceType(e.target.value);
                setPage(1);
              }}
              className="px-3 py-2.5 text-sm bg-gray-50/70 border border-gray-200 rounded-xl focus:bg-white focus:outline-hidden focus:border-[#1463E8] font-medium text-gray-700"
            >
              <option value="all">Tất cả nguồn dữ liệu</option>
              <option value="seed">Curated Seeds (Dữ liệu gốc chuẩn)</option>
              <option value="scraped">Web Scraped (Tự động thu thập)</option>
            </select>

            <button
              type="submit"
              className="px-5 py-2.5 text-sm font-semibold text-white bg-[#1463E8] hover:bg-[#123B86] rounded-xl transition-all shadow-xs shrink-0 flex items-center gap-2"
            >
              <Search className="w-4 h-4" />
              Tìm kiếm
            </button>
          </div>
        </form>

        {/* Category Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 pt-0.5 text-xs">
          <span className="text-gray-400 flex items-center gap-1 font-medium mr-1 shrink-0">
            <Filter className="w-3.5 h-3.5" />
            Lọc theo:
          </span>
          {categories.map((c) => (
            <button
              key={c.id}
              onClick={() => {
                setCategory(c.id);
                setPage(1);
              }}
              className={`px-3 py-1.5 rounded-lg font-medium whitespace-nowrap transition-all ${
                category === c.id
                  ? 'bg-[#1463E8] text-white shadow-2xs'
                  : 'bg-gray-100/80 text-gray-600 hover:bg-gray-200/70'
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Main Knowledge Table / Cards */}
      {loading ? (
        <div className="bg-white rounded-2xl border border-gray-200/90 p-12 text-center shadow-xs">
          <div className="w-10 h-10 border-3 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-3"></div>
          <p className="text-sm font-medium text-gray-600">Đang tra cứu dữ liệu SQLite FTS5...</p>
        </div>
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          title="Không tìm thấy bài viết phù hợp"
          description={`Không có trang nào khớp với từ khóa "${search}" trong danh mục "${category}". Thử tìm với từ khóa khác như "IELTS", "khóa học", hoặc đặt lại bộ lọc.`}
          actionLabel="Xóa bộ lọc & Tải lại"
          onAction={() => {
            setSearch('');
            setCategory('all');
            setSourceType('all');
            setPage(1);
          }}
        />
      ) : (
        <div className="bg-white rounded-2xl border border-gray-200/90 shadow-xs overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="bg-gray-50/80 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  <th className="py-3.5 px-4">Bài viết & Tiêu đề</th>
                  <th className="py-3.5 px-3">Danh mục</th>
                  <th className="py-3.5 px-3">Nguồn</th>
                  <th className="py-3.5 px-3 text-right">Dung lượng</th>
                  <th className="py-3.5 px-3">Cập nhật</th>
                  <th className="py-3.5 px-4 text-center">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.items.map((item) => (
                  <tr key={item.id} className="hover:bg-blue-50/30 transition-colors">
                    <td className="py-3.5 px-4 max-w-md">
                      <div className="font-bold text-gray-900 line-clamp-1">{item.title}</div>
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-[#1463E8] hover:underline flex items-center gap-1 mt-0.5 truncate max-w-sm"
                      >
                        {item.url}
                        <ExternalLink className="w-3 h-3 shrink-0" />
                      </a>
                    </td>

                    <td className="py-3.5 px-3 whitespace-nowrap">
                      <Badge variant="blue">{item.category}</Badge>
                    </td>

                    <td className="py-3.5 px-3 whitespace-nowrap">
                      {item.source_type === 'seed' ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-semibold rounded-md bg-amber-50 text-amber-700 border border-amber-200">
                          <Sparkles className="w-3 h-3 text-amber-500" />
                          Curated Seed
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-medium rounded-md bg-gray-100 text-gray-700">
                          Web Scraped
                        </span>
                      )}
                    </td>

                    <td className="py-3.5 px-3 text-right text-xs text-gray-500 font-mono">
                      {item.content_length ? `${item.content_length.toLocaleString()} ký tự` : '—'}
                    </td>

                    <td className="py-3.5 px-3 text-xs text-gray-500 whitespace-nowrap">
                      {item.updated_at ? item.updated_at.replace('T', ' ').slice(0, 16) : '—'}
                    </td>

                    <td className="py-3.5 px-4 text-center whitespace-nowrap">
                      <button
                        onClick={() => setSelectedItem(item)}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 hover:text-[#1463E8] transition-colors shadow-2xs"
                      >
                        <Eye className="w-3.5 h-3.5 text-gray-500" />
                        Xem trước
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination Footer */}
          <div className="p-4 border-t border-gray-100 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-gray-500">
            <div>
              Hiển thị <strong>{(page - 1) * 12 + 1}</strong> đến{' '}
              <strong>{Math.min(page * 12, data.total)}</strong> trong số <strong>{data.total}</strong> bài viết
            </div>

            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setPage((p) => Math.max(p - 1, 1))}
                disabled={page <= 1}
                className="inline-flex items-center gap-1 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:pointer-events-none font-medium transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                Trang trước
              </button>
              <span className="px-3 py-1.5 font-bold text-gray-800 bg-gray-100 rounded-lg">
                {page} / {data.total_pages || 1}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(p + 1, data.total_pages))}
                disabled={page >= data.total_pages}
                className="inline-flex items-center gap-1 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:pointer-events-none font-medium transition-colors"
              >
                Trang sau
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Article Content Preview Drawer / Modal */}
      {selectedItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/40 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[85vh] flex flex-col shadow-2xl border border-gray-100 overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="p-5 border-b border-gray-100 flex items-start justify-between bg-gradient-to-r from-blue-50/60 to-white">
              <div className="pr-4">
                <div className="flex items-center gap-2 mb-1.5">
                  <Badge variant="blue">{selectedItem.category}</Badge>
                  <Badge variant={selectedItem.source_type === 'seed' ? 'warning' : 'gray'}>
                    {selectedItem.source_type === 'seed' ? 'Curated Seed' : 'Web Scraped'}
                  </Badge>
                </div>
                <h3 className="text-lg font-bold text-gray-900 leading-snug">{selectedItem.title}</h3>
                <a
                  href={selectedItem.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-[#1463E8] hover:underline flex items-center gap-1 mt-1"
                >
                  {selectedItem.url}
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>

              <button
                onClick={() => setSelectedItem(null)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-4 flex-1">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3.5 bg-gray-50 rounded-xl text-xs text-gray-600">
                <div>
                  <div className="text-gray-400">Độ dài nội dung:</div>
                  <div className="font-semibold text-gray-800 mt-0.5 font-mono">
                    {selectedItem.content_length?.toLocaleString() || selectedItem.content.length.toLocaleString()} ký tự
                  </div>
                </div>
                <div>
                  <div className="text-gray-400">Thời gian cập nhật:</div>
                  <div className="font-semibold text-gray-800 mt-0.5">
                    {selectedItem.updated_at ? selectedItem.updated_at.slice(0, 16) : 'N/A'}
                  </div>
                </div>
                <div className="col-span-2">
                  <div className="text-gray-400">SHA-256 Hash:</div>
                  <div className="font-mono text-[11px] text-gray-700 truncate mt-0.5">
                    {selectedItem.content_hash || 'Chưa mã hóa hash'}
                  </div>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
                    <FileText className="w-3.5 h-3.5 text-blue-600" />
                    Nội dung văn bản được lập chỉ mục (Clean Extracted Text)
                  </span>
                  <button
                    onClick={() => handleCopyContent(selectedItem.content)}
                    className="inline-flex items-center gap-1 text-xs text-[#1463E8] hover:text-[#123B86] font-medium"
                  >
                    <Copy className="w-3.5 h-3.5" />
                    Sao chép toàn bộ
                  </button>
                </div>
                <div className="p-4 rounded-xl bg-gray-50/70 border border-gray-200 text-sm text-gray-800 leading-relaxed font-sans whitespace-pre-wrap max-h-96 overflow-y-auto">
                  {selectedItem.content}
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-4 border-t border-gray-100 bg-gray-50/60 flex items-center justify-between">
              <div className="text-xs text-gray-500">
                Dữ liệu được truy vấn trực tiếp từ SQLite FTS5 table `pages`.
              </div>
              <button
                onClick={() => setSelectedItem(null)}
                className="px-4 py-2 text-xs font-semibold text-gray-700 bg-white border border-gray-200 hover:bg-gray-100 rounded-xl transition-colors"
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
