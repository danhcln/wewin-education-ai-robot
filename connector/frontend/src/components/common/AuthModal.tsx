import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../context/ToastContext';
import { Shield, Key, Eye, EyeOff, X, CheckCircle2 } from 'lucide-react';

export const AuthModal: React.FC = () => {
  const { token, saveToken, logout, isAuthModalOpen, closeAuthModal, isValidating, isAuthenticated } = useAuth();
  const toast = useToast();
  const [inputToken, setInputToken] = useState(token);
  const [showToken, setShowToken] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isAuthModalOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputToken.trim()) {
      toast.warning('Vui lòng nhập mã token quản trị viên');
      return;
    }
    setIsSubmitting(true);
    const success = await saveToken(inputToken.trim());
    setIsSubmitting(false);

    if (success) {
      setInputToken('');
      toast.success('Xác thực quản trị viên thành công!');
    } else {
      toast.error('Token không hợp lệ, vui lòng kiểm tra lại');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="bg-white rounded-2xl max-w-md w-full border border-slate-200 shadow-2xl p-6 relative">
        <button
          onClick={closeAuthModal}
          className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
            <Shield className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-bold text-slate-900">Xác thực Quản trị viên</h3>
            <p className="text-xs text-slate-500">Mã Token điều khiển các tác vụ Đồng bộ & Cấu hình</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1.5">
              Admin Sync Token
            </label>
            <div className="relative">
              <Key className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
              <input
                type={showToken ? 'text' : 'password'}
                value={inputToken}
                onChange={(e) => setInputToken(e.target.value)}
                placeholder="Nhập ADMIN_SYNC_TOKEN..."
                className="w-full pl-9 pr-10 py-2.5 text-xs bg-slate-50 border border-slate-200 rounded-xl focus:bg-white focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 font-mono transition-all"
              />
              <button
                type="button"
                onClick={() => setShowToken(!showToken)}
                className="absolute right-3 top-3 text-slate-400 hover:text-slate-600"
              >
                {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            <p className="text-[11px] text-slate-400 mt-1.5 leading-normal">
              Sử dụng token riêng do quản trị viên cấp. Hệ thống không có token mặc định.
            </p>
          </div>

          <div className="p-3 bg-blue-50/60 rounded-xl border border-blue-100 text-xs text-blue-900 flex items-start gap-2.5">
            <CheckCircle2 className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
            <span className="text-[11px] leading-relaxed">
              Đăng nhập được giữ bằng cookie HttpOnly riêng trên máy này, tối đa 7 ngày và cần xác thực lại sau 30 ngày. Mã quản trị không được lưu vào localStorage hoặc sessionStorage sau đăng nhập. Đăng xuất để thu hồi phiên.
            </span>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            {isAuthenticated&&<button type="button" onClick={()=>void logout().then(()=>toast.success('Đã đăng xuất.')).catch(()=>toast.error('Chưa đăng xuất được; thử lại khi backend kết nối.'))} className="px-3 py-2 text-xs text-red-700">Đăng xuất</button>}
            <button
              type="button"
              onClick={closeAuthModal}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 transition-colors"
            >
              Hủy bỏ
            </button>
            <button
              type="submit"
              disabled={isSubmitting || isValidating}
              className="px-5 py-2 rounded-xl text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white shadow-sm transition-all disabled:opacity-50"
            >
              {isSubmitting || isValidating ? 'Đang kiểm tra...' : 'Lưu & Kích hoạt'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
