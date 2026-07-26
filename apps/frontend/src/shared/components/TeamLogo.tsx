import { useState, useEffect } from 'react';
import { getTeamGradient, getTeamLogoUrl } from '../utils/teamLogo';

interface TeamLogoProps {
  /** Team name in Chinese (e.g. "巴塞罗那") */
  nameCn?: string | null;
  /** Team name in English */
  nameEn?: string | null;
  /** Short name (e.g. "巴萨") */
  shortName?: string | null;
  /** Country (e.g. "Spain", "International") */
  country?: string | null;
  /** Original crest URL from team data or a trusted registry. */
  officialLogoUrl?: string | null;
  /** Whether missing crests should fall back to initials. Default true. */
  showFallbackInitials?: boolean;
  /** Logo size in px. Default 48. */
  size?: number;
}

/**
 * Team logo display component.
 *
 * - Local crest registry → bundled team image
 * - Explicit logo URL / country flag → fallback for future unknown teams
 * - Missing logo → square text fallback, never a circular avatar
 */
export default function TeamLogo({
  nameCn,
  nameEn,
  shortName,
  country,
  officialLogoUrl,
  showFallbackInitials = true,
  size = 48,
}: TeamLogoProps) {
  const [imgError, setImgError] = useState(false);

  // Reset error state when team changes (new match)
  useEffect(() => {
    setImgError(false);
  }, [nameCn, nameEn, shortName, country, officialLogoUrl]);

  const logoUrl = getTeamLogoUrl(nameCn, nameEn, country, officialLogoUrl);
  const showLogo = !!logoUrl && !imgError;

  const label = nameCn || nameEn || shortName || 'FC';
  const [c1, c2] = getTeamGradient(label);

  const wrapperStyle: React.CSSProperties = {
    width: size,
    height: size,
    borderRadius: 0,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    flexShrink: 0,
    position: 'relative',
    animation: 'fqpPopIn 0.3s ease both',
    background: 'transparent',
  };

  if (showLogo) {
    return (
      <div
        style={wrapperStyle}
      >
        <img
          src={logoUrl!}
          alt={label}
          style={{
            position: 'relative',
            width: '100%',
            height: '100%',
            objectFit: 'contain',
            borderRadius: 0,
            display: 'block',
          }}
          onError={() => setImgError(true)}
        />
      </div>
    );
  }

  if (!showFallbackInitials) {
    return (
      <div
        style={{
          ...wrapperStyle,
          background: 'rgba(255,255,255,0.03)',
          border: '1px dashed var(--fqp-border-medium)',
          boxShadow: 'none',
        }}
        title={`${label} 暂未配置官方队徽`}
        aria-label={`${label} 暂未配置官方队徽`}
      />
    );
  }

  // Missing crest fallback: reserve a non-circular icon slot without inventing a crest.
  return (
    <div
      style={{
        ...wrapperStyle,
        background: `linear-gradient(135deg, ${c1}, ${c2})`,
        boxShadow: `0 2px 8px ${c1}40`,
      }}
      title={label}
      aria-label={`${label} 暂未配置队徽`}
    >
    </div>
  );
}
