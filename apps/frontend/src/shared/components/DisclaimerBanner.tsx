/** 全局合规免责声明横幅组件。

根据 docs/18_合规与责任博彩提示.md 规范实现。
支持三种类型：
- page: 页内提示（推荐页、实票页、分析页）
- footer: 全局页脚（所有页面底部）
- full: 完整声明（设置/关于页面）
*/

interface DisclaimerBannerProps {
  text?: string;
  type?: 'page' | 'footer' | 'full';
  style?: React.CSSProperties;
}

const PAGE_DEFAULTS: Record<string, string> = {
  recommendations: '本页为模型分析结果，不构成收益承诺。所有推荐基于数学模型和历史数据，历史表现不代表未来结果。',
  tickets: '用户需通过合法合规体彩实体店自行购买，本系统仅记录上传信息。系统不提供互联网售彩、代购、合买、出票、收款、自动下单等服务。',
  bankroll: '每日预算为风险上限，不建议超预算或追单。连续亏损触发降仓机制，连续亏损7天将转为仅模拟模式。',
  reports: '历史表现不代表未来结果。所有统计数据仅供研究和策略评估参考。',
  pool: '传统足彩14场/任九为概率模型研究工具，不构成投注建议。所有概率基于数学估计，不等于实际结果。请通过体彩实体店购买。',
  dashboard: '本系统仅用于数据采集、概率模型研究、模拟投注、线下自购记录、赛后复盘与长期策略评估。',
};

const FOOTER_TEXT =
  'FQP 足球量化分析系统 — 仅供数据分析与学术研究。不提供互联网售彩、代购、合买、出票、收款、自动下单等服务。请通过合法合规体彩实体店购买。';

const FULL_DISCLAIMER = `## 系统边界

本系统仅用于数据采集、概率模型研究、模拟投注、线下自购记录、赛后复盘与长期策略评估。系统不提供互联网售彩、代购、合买、出票、收款、自动下单等服务。

## 禁止表达

本系统及其输出中不使用以下表述：必中、稳赚、包红、内幕、保本、稳定盈利、专家带单、自动出票、线上购彩。

## 责任规则

- 连续亏损触发降仓
- 连续亏损7天只模拟
- 用户超预算时系统提示
- 实验池不得影响主策略资金
- 比分/半全场等高波动玩法默认小额或模拟

## 法律依据

- 国家体育总局《体彩30年老规矩 买彩票只认体彩实体店》
- 财政部《未经批准任何单位不得网销售彩票》
- 中国体育彩票仅通过合法实体店销售，擅自利用互联网销售属非法彩票`;

export default function DisclaimerBanner({
  text,
  type = 'page',
  style,
}: DisclaimerBannerProps) {
  if (type === 'footer') {
    return (
      <footer
        style={{
          padding: '12px 24px',
          borderTop: '1px solid var(--fqp-border)',
          fontSize: '11px',
          color: 'var(--fqp-text-muted)',
          textAlign: 'center',
          background: 'rgba(0,0,0,0.2)',
          lineHeight: '1.8',
          ...style,
        }}
      >
        <div>{FOOTER_TEXT}</div>
      </footer>
    );
  }

  if (type === 'full') {
    return (
      <div
        style={{
          padding: '20px',
          background: 'rgba(39,39,42,0.3)',
          border: '1px solid var(--fqp-border)',
          borderRadius: '8px',
          fontSize: '13px',
          color: 'var(--fqp-text-muted)',
          lineHeight: '1.8',
          whiteSpace: 'pre-wrap',
          ...style,
        }}
      >
        {FULL_DISCLAIMER}
      </div>
    );
  }

  // type === 'page'
  return (
    <div
      style={{
        padding: '10px 16px',
        marginBottom: '16px',
        background: 'rgba(99,102,241,0.08)',
        border: '1px solid rgba(99,102,241,0.25)',
        borderRadius: '6px',
        fontSize: '12px',
        color: 'var(--fqp-text-muted)',
        lineHeight: '1.6',
        display: 'flex',
        alignItems: 'flex-start',
        gap: '8px',
        ...style,
      }}
    >
      <span style={{ flexShrink: 0, fontSize: '14px' }}>ℹ️</span>
      <span>{text}</span>
    </div>
  );
}

export { PAGE_DEFAULTS, FOOTER_TEXT, FULL_DISCLAIMER };
