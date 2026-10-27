import type { ReactNode } from 'react';
import { useLanguage } from '../../app/LanguageContext';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  lastUpdated?: string;
  actions?: ReactNode;
}

export default function PageHeader({ title, subtitle, lastUpdated, actions }: PageHeaderProps) {
  const { translate } = useLanguage();
  return (
    <div className="fqp-page-header">
      <div className="fqp-page-heading">
        <h1 className="fqp-page-title">{translate(title)}</h1>
        {(subtitle || lastUpdated) && <div className="fqp-page-subtitle">
          {subtitle && translate(subtitle)}
          {subtitle && lastUpdated ? ' · ' : ''}
          {lastUpdated ? `${translate('最后更新')}: ${lastUpdated}` : ''}
        </div>}
      </div>
      {actions && <div className="fqp-page-actions">{actions}</div>}
    </div>
  );
}
