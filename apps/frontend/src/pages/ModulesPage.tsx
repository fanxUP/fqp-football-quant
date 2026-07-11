import { useEffect, useState } from 'react';
import { api, type RuntimeModule } from '../core/apiClient';
import { MODULE_REGISTRY, NAVIGATION_GROUPS, type ModuleManifest } from '../panelRegistry';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';
import Modal from '../shared/components/Modal';
import { useLocalSettings } from '../shared/hooks/useLocalSettings';

type ModuleView = ModuleManifest & {
  disabled: boolean;
  safeDisable: boolean;
};

function enrichRuntimeModule(module: RuntimeModule): ModuleView {
  const staticModule = MODULE_REGISTRY.find((item) => item.moduleCode === module.moduleCode);
  return {
    moduleCode: module.moduleCode,
    moduleName: module.moduleName,
    description: staticModule?.description ?? module.moduleName,
    version: staticModule?.version ?? 'runtime',
    category: module.category,
    status: module.status === 'disabled' ? 'inactive' : module.status,
    required: module.required,
    panels: module.panels,
    dependencies: module.dependsOn,
    disabled: module.disabled,
    safeDisable: module.safeDisable,
  };
}

export default function ModulesPage() {
  const { settings, updateSetting } = useLocalSettings();
  const [runtimeModules, setRuntimeModules] = useState<ModuleView[] | null>(null);
  const [selected, setSelected] = useState<ModuleView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.ui.modules()
      .then((resp) => {
        if (!cancelled) setRuntimeModules(resp.modules.map(enrichRuntimeModule));
      })
      .catch(() => {
        if (!cancelled) setRuntimeModules(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const modules = runtimeModules ?? MODULE_REGISTRY.map((mod) => ({
    ...mod,
    disabled: settings.disabledModules.includes(mod.moduleCode),
    safeDisable: !mod.required,
  }));

  const selectedModule = selected
    ? modules.find((mod) => mod.moduleCode === selected.moduleCode) ?? selected
    : null;

  const isDisabled = (code: string) => modules.some((mod) => mod.moduleCode === code && mod.disabled);

  const localToggleModule = (code: string) => {
    const next = settings.disabledModules.includes(code)
      ? settings.disabledModules.filter((m) => m !== code)
      : [...settings.disabledModules, code];
    updateSetting('disabledModules', next);
  };

  const toggleModule = async (code: string) => {
    const mod = modules.find((item) => item.moduleCode === code);
    if (!mod) return;
    setError(null);
    if (!runtimeModules) {
      localToggleModule(code);
      window.dispatchEvent(new Event('fqp-modules-updated'));
      return;
    }
    try {
      const resp = await api.ui.setModuleStatus(code, { disabled: !mod.disabled });
      setRuntimeModules((prev) =>
        (prev ?? modules).map((item) =>
          item.moduleCode === code ? enrichRuntimeModule(resp.module) : item,
        ),
      );
      window.dispatchEvent(new Event('fqp-modules-updated'));
    } catch (err) {
      const message = err instanceof Error ? err.message : '模块状态更新失败';
      setError(message);
    }
  };

  const statusBadge = (mod: ModuleView) => {
    if (mod.status === 'coming_soon') return <StatusBadge status="disabled" label="待开发" />;
    if (mod.disabled) return <StatusBadge status="error" label="已禁用" />;
    if (mod.required) return <StatusBadge status="ok" label="核心" />;
    return <StatusBadge status="ok" label="运行中" />;
  };

  return (
    <div>
      <PageHeader title="模块管理" />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '28px', marginBottom: '24px' }}>
        {NAVIGATION_GROUPS.map((group) => {
          const groupedModules = modules.filter((mod) => mod.category === group.groupCode);
          if (groupedModules.length === 0) return null;

          return (
            <section key={group.groupCode}>
              <div
                style={{
                  fontSize: '13px',
                  fontWeight: 700,
                  color: 'var(--fqp-text-muted)',
                  marginBottom: '12px',
                }}
              >
                {group.groupName}
              </div>
              <div className="fqp-grid-2">
                {groupedModules.map((mod, i) => (
                  <Card
                    key={mod.moduleCode}
                    title={mod.moduleName}
                    action={statusBadge(mod)}
                    onClick={() => setSelected(mod)}
                    style={{
                      cursor: 'pointer',
                      animation: `fqpCardEnter 0.4s ease both`,
                      animationDelay: `${(group.order + i) * 20}ms`,
                    }}
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
            </section>
          );
        })}
      </div>

      {/* Module detail modal */}
      <Modal
        open={!!selected}
        onClose={() => setSelected(null)}
        title={selectedModule?.moduleName || ''}
        footer={
          selectedModule && selectedModule.status !== 'coming_soon' ? (
            <>
              <button className="fqp-btn" onClick={() => setSelected(null)}>
                关闭
              </button>
              {!selectedModule.required && (
                <button
                  className={`fqp-btn ${isDisabled(selectedModule.moduleCode) ? 'fqp-btn-primary' : 'fqp-btn-danger'}`}
                  onClick={() => {
                    void toggleModule(selectedModule.moduleCode);
                  }}
                >
                  {isDisabled(selectedModule.moduleCode) ? '启用模块' : '禁用模块'}
                </button>
              )}
            </>
          ) : (
            <button className="fqp-btn" onClick={() => setSelected(null)}>
              关闭
            </button>
          )
        }
      >
        {selectedModule && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {error && (
              <div
                style={{
                  padding: '12px',
                  background: 'rgba(239,68,68,0.08)',
                  border: '1px solid rgba(239,68,68,0.24)',
                  borderRadius: 'var(--fqp-radius-sm)',
                  fontSize: '13px',
                  color: 'var(--fqp-danger)',
                }}
              >
                {error}
              </div>
            )}
            <div>
              <div className="fqp-label">描述</div>
              <div style={{ fontSize: '13px' }}>{selectedModule.description}</div>
            </div>
            <div>
              <div className="fqp-label">版本</div>
              <div className="fqp-mono">{selectedModule.version}</div>
            </div>
            <div>
              <div className="fqp-label">状态</div>
              {statusBadge(selectedModule)}
            </div>
            <div>
              <div className="fqp-label">模块分层</div>
              <div style={{ fontSize: '13px' }}>
                {NAVIGATION_GROUPS.find((group) => group.groupCode === selectedModule.category)?.groupName}
              </div>
            </div>
            {selectedModule.panels.length > 0 && (
              <div>
                <div className="fqp-label">注册面板 ({selectedModule.panels.length})</div>
                <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
                  {selectedModule.panels.join(', ')}
                </div>
              </div>
            )}
            {selectedModule.dependencies.length > 0 && (
              <div>
                <div className="fqp-label">依赖模块 ({selectedModule.dependencies.length})</div>
                <div style={{ fontSize: '13px', color: 'var(--fqp-text-muted)' }}>
                  {selectedModule.dependencies.join(', ')}
                </div>
              </div>
            )}
            {selectedModule.status === 'coming_soon' && (
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
