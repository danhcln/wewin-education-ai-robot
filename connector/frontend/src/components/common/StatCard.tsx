import React from 'react';
import type { LucideIcon } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string | number;
  subValue?: string;
  icon: LucideIcon;
  iconColor?: string;
  iconBg?: string;
  badgeText?: string;
  badgeVariant?: 'success' | 'warning' | 'danger' | 'primary' | 'neutral';
  onClick?: () => void;
  className?: string;
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subValue,
  icon: Icon,
  iconColor = 'text-blue-600',
  iconBg = 'bg-blue-50',
  badgeText,
  badgeVariant = 'neutral',
  onClick,
  className = ''
}) => {
  return (
    <div
      onClick={onClick}
      className={`bg-white rounded-2xl p-5 border border-slate-200/80 shadow-sm hover:shadow-md transition-all duration-200 ${
        onClick ? 'cursor-pointer hover:border-blue-300' : ''
      } ${className}`}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">{title}</p>
          <h3 className="text-2xl font-bold text-slate-900 mt-1.5 tracking-tight">{value}</h3>
          {subValue && (
            <p className="text-xs text-slate-500 mt-1 font-normal flex items-center gap-1.5">
              {subValue}
            </p>
          )}
        </div>
        <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${iconBg}`}>
          <Icon className={`w-5 h-5 ${iconColor}`} />
        </div>
      </div>

      {badgeText && (
        <div className="mt-3.5 pt-3 border-t border-slate-100 flex items-center justify-between">
          <span
            className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${
              badgeVariant === 'success'
                ? 'bg-emerald-50 text-emerald-700'
                : badgeVariant === 'warning'
                ? 'bg-amber-50 text-amber-700'
                : badgeVariant === 'danger'
                ? 'bg-rose-50 text-rose-700'
                : 'bg-blue-50 text-blue-700'
            }`}
          >
            {badgeText}
          </span>
        </div>
      )}
    </div>
  );
};
