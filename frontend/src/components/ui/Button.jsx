import React from 'react';
import { cn } from '../../lib/cn';

const variants = {
  primary: 'bg-[#0d9488] text-white hover:bg-[#0f766e] focus-visible:ring-[#0d9488]/50',
  secondary: 'bg-white text-slate-900 border border-slate-200 hover:bg-slate-50 focus-visible:ring-slate-300',
  danger: 'bg-rose-600 text-white hover:bg-rose-700 focus-visible:ring-rose-500/50',
};

const sizes = {
  sm: 'h-9 px-3 text-sm',
  md: 'h-11 px-4 text-sm',
  lg: 'h-12 px-6 text-base',
};

export default function Button({
  children,
  className,
  variant = 'primary',
  size = 'md',
  type = 'button',
  ...props
}) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex items-center justify-center rounded-xl font-semibold transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-4',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
