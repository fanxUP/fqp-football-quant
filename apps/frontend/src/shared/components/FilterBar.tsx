import type { ReactNode } from 'react';

interface FilterBarProps {
  children: ReactNode;
}

export default function FilterBar({ children }: FilterBarProps) {
  return <div className="fqp-filter-bar">{children}</div>;
}
