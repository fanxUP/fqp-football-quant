/** Generic page note banner. Kept for legacy screens that need compact notices. */

interface DisclaimerBannerProps {
  text?: string;
  type?: 'page' | 'footer' | 'full';
  style?: React.CSSProperties;
}

const PAGE_DEFAULTS: Record<string, string> = {
  recommendations: '推荐票单按模型输出、赔率变化和赛果复盘统一归档。',
  tickets: '彩票按购买日期归档，并自动汇总票面、结算、盈亏和 ROI。',
  bankroll: '资金账户记录投入、返奖、调整和结算流水。',
  reports: '复盘中心汇总日报、周报、月报、结算记录和错因分析。',
  pool: '传统足彩14场/任九按策略、概率分布和组合成本组织方案。',
  dashboard: '驾驶舱汇总比赛、预测、推荐、彩票和 Agent 资金池状态。',
};

const FOOTER_TEXT =
  'FQP 足球量化分析系统';

const FULL_DISCLAIMER = `## 系统说明

系统围绕比赛数据、模型预测、投注台、彩票台账和赛后复盘组织工作流。

## 核心模块

- 投注台：官方赛事选号、混合过关、投注确认和理论奖金
- 彩票：我的彩票与 Agent 彩票按日期归档
- 比赛结果：结算后的盈亏、ROI 和命中表现
- 复盘中心：日报、周报、月报与错因分析`;

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
          background: 'var(--fqp-border-light)',
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
      className="fqp-anim-slideLeft"
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
