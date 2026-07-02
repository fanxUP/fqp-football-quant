import type { ReactNode } from 'react';
import Sidebar from './Sidebar';
import DisclaimerBanner from '../../shared/components/DisclaimerBanner';

interface LayoutProps {
  children: ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div className="fqp-layout">
      <Sidebar />
      <main className="fqp-main">
        {children}
        <DisclaimerBanner type="footer" />
      </main>
    </div>
  );
}
