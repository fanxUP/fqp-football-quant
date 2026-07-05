import { useState } from 'react';
import { MODULE_REGISTRY, type ModuleManifest } from '../panelRegistry';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';
import Modal from '../shared/components/Modal';
import { useLocalSettings } from '../shared/hooks/useLocalSettings';

export default function ModulesPage() {
  const { settings, updateSetting } = useLocalSettings();
  const [selected, setSelected] = useState<ModuleManifest | null>(null);

  const isDisabled = (code: string) => settings.disabledModules.includes(code);

  const toggleModule = (code: string) => {
    const next = isDisabled(code)
      ? settings.disabledModules.filter((m) => m !== code)
      : [...settings.disabledModules, code];
    updateSetting('disabledModules', next);
  };

  const statusBadge = (mod: ModuleManifest) => {
    if (mod.status === 'coming_soon') return <StatusBadge status="disabled" label="待开发" />;
    if (isDisabled(mod.moduleCode)) return <StatusBadge status="error" label="已禁用" />;
    return <StatusBadge status="ok" label="运行中" />;
  };

  return (
    <div>
      <PageHeader title="模块管理" />

      <div className="fqp-grid-2" style={{ marginBottom: '24px' }}>
        {MODULE_REGISTRY.map((mod, i) => (
          <Card
            key={mod.moduleCode}
            title={mod.moduleName}
            action={statusBadge(mod)}
            onClick={() => setSelected(mod)}
            style={{ cursor: 'pointer', animation: `fqpCardEnter 0.4s ease both`, animationDelay: `${i * 60}ms` }}
          >
            <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)', marginBottom: '12px' }}>
              {mod.description}
            </div>
            <div style={{ display: 'flex', gap: '16px', fontSize: '12px' }}>
              <span style={{ color: 'var(--fqp-text-muted)' }}>
                版本: <span className="fqp-mono">{mod.version}</span>
              </span>
              <span style={{ color: 'var(--fqp-text-muted)' }}>
                面板: <span className="fqp-mono">{mod.panels.length}</span>
              </span>
              <span style={{ color: 'var(--fqp-text-muted)' }}>
                依赖: <span className="fqp-mono">{mod.dependencies.length}</span>
              </span>
            </div>
          </Card>
        ))}
      </div>

      {/* Module detail modal */}
      <Modal
        open={!!selected}
        onClose={() => setSelected(null)}
        title={selected?.moduleName || ''}
        footer={
          selected && selected.status !== 'coming_soon' ? (
            <>
              <button className="fqp-btn" onClick={() => setSelected(null)}>
                关闭
              </button>
              <button
                className={`fqp-btn ${isDisabled(selected.moduleCode) ? 'fqp-btn-primary' : 'fqp-btn-danger'}`}
                onClick={() => {
                  toggleModule(selected.moduleCode);
                  setSelected(null);
                }}
              >
                {isDisabled(selected.moduleCode) ? '启用模块' : '禁用模块'}
              </button>
            </>
          ) : (
            <button className="fqp-btn" onClick={() => setSelected(null)}>
              关闭
            </button>
          )
        }
      >
        {selected && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div>
              <div className="fqp-label">描述</div>
              <div style={{ fontSize: '13px' }}>{selected.description}</div>
            </div>
            <div>
              <div className="fqp-label">版本</div>
              <div className="fqp-mono">{selected.version}</div>
            </div>
            <div>
              <div className="fqp-label">状态</div>
              {statusBadge(selected)}
            </div>
            {selected.panels.length > 0 && (
              <div>
                <div className="fqp-label">注册面板 ({selected.panels.length})</div>
                <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
                  {selected.panels.join(', ')}
                </div>
              </div>
            )}
            {selected.dependencies.length > 0 && (
              <div>
                <div className="fqp-label">依赖模块 ({selected.dependencies.length})</div>
                <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
                  {selected.dependencies.join(', ')}
                </div>
              </div>
            )}
            {selected.status === 'coming_soon' && (
              <div
                style={{
                  padding: '12px',
                  background: 'rgba(245,165,36,0.08)',
                  border: '1px solid rgba(245,165,36,0.2)',
                  borderRadius: 'var(--fqp-radius-sm)',
                  fontSize: '13px',
                  color: 'var(--fqp-warning)',
                }}
              >
                该模块尚未实现，将在后续阶段开发。
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
