import React from 'react';
import { cn } from '../../lib/cn';

export default function Card({ children, className }) {
  return (
    <div
      className={cn(
        'rounded-2xl border border-slate-200 bg-white/90 p-6 shadow-[0_10px_30px_rgba(2,6,23,0.06)] backdrop-blur-sm',
        className,
      )}
    >
      {children}
    </div>
  );
}
