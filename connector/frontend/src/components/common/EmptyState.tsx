import { Database, SearchX, Inbox } from 'lucide-react';

interface EmptyStateProps {
  title: string;
  description: string;
  actionText?: string;
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
  icon?: 'search' | 'database' | 'inbox';
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  actionText,
  actionLabel,
  onAction,
  className = '',
  icon = 'search'
}) => {
  const btnText = actionLabel || actionText;

  const renderIcon = () => {
    switch (icon) {
      case 'database':
        return <Database className="w-8 h-8 text-[#1463E8]" />;
      case 'inbox':
        return <Inbox className="w-8 h-8 text-[#1463E8]" />;
      case 'search':
      default:
        return <SearchX className="w-8 h-8 text-[#1463E8]" />;
    }
  };

  return (
    <div className={`flex flex-col items-center justify-center text-center p-10 sm:p-12 bg-white rounded-2xl border border-slate-200/80 shadow-2xs ${className}`}>
      {/* Modern SaaS Layered Icon Badge */}
      <div className="relative mb-4">
        <div className="w-16 h-16 rounded-2xl bg-blue-50 border border-blue-100 flex items-center justify-center shadow-xs">
          {renderIcon()}
        </div>
        <div className="absolute -inset-2 rounded-3xl bg-blue-50/50 -z-10 pointer-events-none" />
      </div>

      <h3 className="text-base font-bold text-slate-900 tracking-tight mb-1">
        {title}
      </h3>
      <p className="text-xs text-slate-500 max-w-sm leading-relaxed mb-5">
        {description}
      </p>
      {btnText && onAction && (
        <button
          onClick={onAction}
          className="inline-flex items-center gap-2 px-4.5 py-2 rounded-xl text-xs font-semibold bg-[#1463E8] hover:bg-[#123B86] text-white shadow-xs transition-all active:scale-95"
        >
          {btnText}
        </button>
      )}
    </div>
  );
};
