import { useState, useEffect } from 'react';
import { getFlagUrl, getTeamGradient, getTeamInitials } from '../utils/teamLogo';

interface TeamLogoProps {
  /** Team name in Chinese (e.g. "巴塞罗那") */
  nameCn?: string | null;
  /** Team name in English */
  nameEn?: string | null;
  /** Short name (e.g. "巴萨") */
  shortName?: string | null;
  /** Country (e.g. "Spain", "International") */
  country?: string | null;
  /** Logo size in px. Default 48. */
  size?: number;
}

/**
 * Team logo display component.
 *
 * - National teams → flag image from flagcdn.com, rounded circle
 * - Club teams    → colored gradient circle with initials
 * - Handles image load error → graceful fallback to initials
 */
export default function TeamLogo({
  nameCn,
  nameEn,
  shortName,
  country,
  size = 48,
}: TeamLogoProps) {
  const [imgError, setImgError] = useState(false);

  // Reset error state when team changes (new match)
  useEffect(() => {
    setImgError(false);
  }, [nameCn, nameEn, shortName, country]);

  const flagUrl = getFlagUrl(nameCn, nameEn, country);
  const showFlag = !!flagUrl && !imgError;

  const label = nameCn || nameEn || shortName || 'FC';
  const initials = getTeamInitials(nameCn, shortName, nameEn);
  const [c1, c2] = getTeamGradient(label);
  const fontSize = Math.max(11, Math.round(size * 0.35));

  const wrapperStyle: React.CSSProperties = {
    width: size,
    height: size,
    borderRadius: '50%',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    flexShrink: 0,
    position: 'relative',
    animation: 'fqpPopIn 0.3s ease both',
    transition: 'transform 0.2s ease',
  };

  if (showFlag) {
    return (
      <div
        style={wrapperStyle}
        onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.1) rotate(-3deg)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1) rotate(0deg)'; }}
      >
        {/* Background gradient (visible while image loads) */}
        <div style={{
          position: 'absolute', inset: 0,
          borderRadius: '50%',
          background: `linear-gradient(135deg, ${c1}, ${c2})`,
          opacity: 1,
        }} />
        <img
          src={flagUrl!}
          alt={label}
          style={{
            position: 'relative',
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            borderRadius: '50%',
            display: 'block',
          }}
          onError={() => setImgError(true)}
        />
        {/* Subtle rim */}
        <div style={{
          position: 'absolute', inset: 0,
          borderRadius: '50%',
          border: '1px solid rgba(255,255,255,0.12)',
          pointerEvents: 'none',
        }} />
      </div>
    );
  }

  // Club team or fallback: gradient circle with initials
  return (
    <div
      style={{
        ...wrapperStyle,
        background: `linear-gradient(135deg, ${c1}, ${c2})`,
        boxShadow: `0 2px 8px ${c1}40`,
      }}
      title={label}
      onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.1) rotate(-3deg)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1) rotate(0deg)'; }}
    >
      <span style={{
        fontSize,
        fontWeight: 700,
        color: '#fff',
        textShadow: '0 1px 3px rgba(0,0,0,0.3)',
        lineHeight: 1,
        letterSpacing: '0.02em',
      }}>
        {initials}
      </span>
      {/* Subtle inner highlight */}
      <div style={{
        position: 'absolute', top: '8%', left: '15%',
        width: '40%', height: '30%',
        borderRadius: '50%',
        background: 'radial-gradient(ellipse, rgba(255,255,255,0.2) 0%, transparent 70%)',
        pointerEvents: 'none',
      }} />
    </div>
  );
}
