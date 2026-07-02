import type { ReactNode } from 'react';
import Sidebar from './Sidebar';

interface LayoutProps {
  children: ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div className="fqp-layout">
      <Sidebar />
      <main className="fqp-main">{children}</main>
    </div>
  );
}
