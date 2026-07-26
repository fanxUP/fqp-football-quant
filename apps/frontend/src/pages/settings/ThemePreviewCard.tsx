import type { ThemeDefinition } from '../../theme/types';

interface ThemePreviewCardProps {
  theme: ThemeDefinition;
  selected: boolean;
  onSelect: () => void;
}

export default function ThemePreviewCard({ theme, selected, onSelect }: ThemePreviewCardProps) {
  const label = `${theme.name}，${theme.description}${theme.available ? '' : '，规划中'}`;
  return (
    <button
      type="button"
      className="theme-preview-card"
      data-selected={selected}
      disabled={!theme.available}
      aria-label={label}
      aria-pressed={theme.available ? selected : undefined}
      onClick={onSelect}
    >
      <span className="theme-preview-canvas" style={{ background: theme.preview.background }} aria-hidden="true">
        <span className="theme-preview-sidebar" style={{ background: theme.preview.surface }} />
        <span className="theme-preview-content">
          <span className="theme-preview-metric" style={{ background: theme.preview.surface }}>
            <i style={{ background: theme.preview.primary }} />
            <b style={{ color: theme.preview.primary }}>68.4%</b>
          </span>
          <span className="theme-preview-chart" style={{ background: theme.preview.surface }}>
            <svg viewBox="0 0 120 34" preserveAspectRatio="none">
              <polyline points="0,28 22,22 43,25 66,12 88,17 120,5" fill="none" stroke={theme.preview.primary} strokeWidth="3" />
              <polyline points="0,18 22,25 43,17 66,22 88,10 120,14" fill="none" stroke={theme.preview.secondary} strokeWidth="2" />
            </svg>
          </span>
        </span>
      </span>
      <span className="theme-preview-copy">
        <strong>{theme.name}</strong>
        <span>{theme.description}</span>
      </span>
      <span className="theme-preview-status">
        {selected ? '● 正在预览' : theme.available ? '可用' : '后续开放'}
      </span>
    </button>
  );
}
