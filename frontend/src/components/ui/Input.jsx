import React from 'react';
import { cn } from '../../lib/cn';

export default function Input({ className, ...props }) {
  return (
    <input
      className={cn(
        'h-11 w-full rounded-xl border border-slate-300 bg-white px-3.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-[#0d9488] focus:ring-4 focus:ring-[#0d9488]/20',
        className,
      )}
      {...props}
    />
  );
}
