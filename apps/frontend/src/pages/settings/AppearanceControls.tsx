import type { AppearanceSettings } from '../../theme/types';
import SegmentedControl from './SegmentedControl';

interface AppearanceControlsProps {
  settings: AppearanceSettings;
  onChange: (patch: Partial<AppearanceSettings>) => void;
}

export default function AppearanceControls({ settings, onChange }: AppearanceControlsProps) {
  return (
    <div className="appearance-controls-grid">
      <SegmentedControl
        label="信息密度"
        value={settings.density}
        onChange={(density) => onChange({ density })}
        options={[
          { value: 'comfortable', label: '宽松', description: '更大留白' },
          { value: 'standard', label: '标准', description: '日常使用' },
          { value: 'compact', label: '紧凑', description: '显示更多' },
          { value: 'terminal', label: '专业终端', description: '最高密度' },
        ]}
      />
      <SegmentedControl
        label="页面圆角"
        value={settings.radius}
        onChange={(radius) => onChange({ radius })}
        options={[
          { value: 'square', label: '直角专业' },
          { value: 'subtle', label: '轻圆角' },
          { value: 'soft', label: '柔和圆角' },
        ]}
      />
      <SegmentedControl
        label="动效等级"
        value={settings.motion}
        onChange={(motion) => onChange({ motion, reduceMotion: motion === 'off' })}
        options={[
          { value: 'off', label: '关闭' },
          { value: 'light', label: '轻量' },
          { value: 'standard', label: '标准' },
          { value: 'immersive', label: '沉浸' },
        ]}
      />
      <SegmentedControl
        label="卡片样式"
        value={settings.cardStyle}
        onChange={(cardStyle) => onChange({ cardStyle })}
        options={[
          { value: 'flat', label: '平面' },
          { value: 'bordered', label: '描边' },
          { value: 'elevated', label: '悬浮' },
          { value: 'glass', label: '半透明' },
          { value: 'glow', label: '微光' },
        ]}
      />
      <div className="appearance-select-grid">
        <label>
          <span>侧边栏模式</span>
          <select value={settings.sidebarMode} onChange={(event) => onChange({ sidebarMode: event.target.value as AppearanceSettings['sidebarMode'] })}>
            <option value="expanded">完整展开</option>
            <option value="compact">紧凑显示</option>
            <option value="icons">仅图标</option>
            <option value="auto">跟随屏幕</option>
          </select>
        </label>
        <label>
          <span>数字字体</span>
          <select value={settings.numberFont} onChange={(event) => onChange({ numberFont: event.target.value as AppearanceSettings['numberFont'] })}>
            <option value="default">默认字体</option>
            <option value="mono">等宽数字</option>
            <option value="display">展示字体</option>
          </select>
        </label>
        <label>
          <span>盈利与风险颜色</span>
          <select value={settings.financialColorMode} onChange={(event) => onChange({ financialColorMode: event.target.value as AppearanceSettings['financialColorMode'] })}>
            <option value="semantic">语义色</option>
            <option value="cn-finance">中国金融习惯</option>
            <option value="global-finance">国际金融习惯</option>
            <option value="colorblind-safe">色弱友好</option>
          </select>
        </label>
        <label>
          <span>图表样式</span>
          <select value={settings.chartStyle} onChange={(event) => onChange({ chartStyle: event.target.value as AppearanceSettings['chartStyle'] })}>
            <option value="professional">专业</option>
            <option value="minimal">极简</option>
            <option value="glow">微光</option>
          </select>
        </label>
      </div>
      <div className="appearance-switches">
        <label>
          <input type="checkbox" checked={settings.backgroundEffect} onChange={(event) => onChange({ backgroundEffect: event.target.checked })} />
          <span>启用主题背景效果</span>
        </label>
        <label>
          <input type="checkbox" checked={settings.reduceMotion} onChange={(event) => onChange({ reduceMotion: event.target.checked })} />
          <span>减少动态效果</span>
        </label>
      </div>
    </div>
  );
}
