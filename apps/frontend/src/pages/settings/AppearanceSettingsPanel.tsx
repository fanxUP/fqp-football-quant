import { useEffect } from 'react';
import { useTheme } from '../../app/ThemeContext';
import { DEFAULT_APPEARANCE_SETTINGS } from '../../theme/defaults';
import { THEME_REGISTRY } from '../../theme/themeRegistry';
import type { AppearanceSettings, ThemeCategory } from '../../theme/types';
import { toast } from '../../shared/components/Toast';
import AppearanceControls from './AppearanceControls';
import ThemePreviewCard from './ThemePreviewCard';

const GROUPS: Array<{ id: ThemeCategory; label: string; description: string }> = [
  { id: 'professional', label: '专业量化', description: '资金、模型与系统运行' },
  { id: 'football', label: '足球赛事', description: '比赛日、战术与赛事大屏' },
  { id: 'future', label: '科技未来', description: '人工智能、智能代理与自动化链路' },
  { id: 'personal', label: '个性主题', description: '浅色办公与年轻化表达' },
];

export default function AppearanceSettingsPanel() {
  const {
    appearance,
    previewAppearance,
    commitAppearance,
    cancelPreview,
    isPreviewing,
  } = useTheme();

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isPreviewing) cancelPreview();
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [cancelPreview, isPreviewing]);

  const previewPatch = (patch: Partial<AppearanceSettings>) => {
    previewAppearance({ ...appearance, ...patch });
  };

  const apply = () => {
    commitAppearance();
    toast.success('外观设置已应用');
  };

  const cancel = () => {
    cancelPreview();
    toast.warning('已取消外观预览');
  };

  return (
    <section className="appearance-panel" aria-labelledby="appearance-title">
      <div className="appearance-panel-heading">
        <div>
          <span className="appearance-eyebrow">外观系统</span>
          <h2 id="appearance-title">外观与显示</h2>
          <p>选择符合使用场景的视觉语言，数据结构与业务状态保持不变。</p>
        </div>
        <div className="appearance-live-status" aria-live="polite">
          <i /> {isPreviewing ? '实时预览中，尚未保存' : '当前设置已保存'}
        </div>
      </div>

      <div className="theme-gallery">
        {GROUPS.map((group) => (
          <section className="theme-group" key={group.id} aria-labelledby={`theme-group-${group.id}`}>
            <div className="theme-group-heading">
              <h3 id={`theme-group-${group.id}`}>{group.label}</h3>
              <span>{group.description}</span>
            </div>
            <div className="theme-card-grid">
              {THEME_REGISTRY.filter((theme) => theme.category === group.id).map((theme) => (
                <ThemePreviewCard
                  key={theme.id}
                  theme={theme}
                  selected={appearance.theme === theme.id}
                  onSelect={() => previewPatch({ theme: theme.id, ...theme.defaults })}
                />
              ))}
            </div>
          </section>
        ))}
      </div>

      <div className="appearance-divider" />
      <AppearanceControls settings={appearance} onChange={previewPatch} />

      <div className="appearance-actions">
        <button type="button" className="fqp-btn" onClick={() => previewAppearance({ ...DEFAULT_APPEARANCE_SETTINGS })}>恢复推荐默认</button>
        <span className="appearance-action-spacer" />
        <button type="button" className="fqp-btn" onClick={cancel} disabled={!isPreviewing}>取消预览</button>
        <button type="button" className="fqp-btn fqp-btn-primary" onClick={apply} disabled={!isPreviewing}>应用外观设置</button>
      </div>
    </section>
  );
}
