/** Generic skeleton placeholder with shimmer animation.
 *  Replaces LoadingSpinner in most loading scenarios.
 */
import type { ReactNode } from 'react';

interface SkeletonProps {
  variant?: 'text' | 'card' | 'circle' | 'table-row';
  width?: string | number;
  height?: string | number;
  size?: number;       // circle diameter
  count?: number;      // repeat for table rows
  style?: Record<string, string | number>;
}

function toPx(v: string | number | undefined, fallback: string): string {
  if (v === undefined) return fallback;
  if (typeof v === 'number') return `${v}px`;
  return v;
}

export default function Skeleton({
  variant = 'text',
  width,
  height,
  size = 40,
  count = 1,
  style,
}: SkeletonProps) {
  const items: ReactNode[] = [];

  for (let i = 0; i < count; i++) {
    switch (variant) {
      case 'circle':
        items.push(
          <div
            key={i}
            className="fqp-skeleton"
            style={{
              width: toPx(size, '40px'),
              height: toPx(size, '40px'),
              borderRadius: '50%',
              flexShrink: 0,
              ...style,
            }}
          />,
        );
        break;

      case 'card':
        items.push(
          <div
            key={i}
            className="fqp-skeleton"
            style={{
              width: toPx(width, '100%'),
              height: toPx(height, '120px'),
              borderRadius: 'var(--fqp-radius-card)',
              ...style,
            }}
          />,
        );
        break;

      case 'table-row':
        items.push(
          <div
            key={i}
            className="fqp-skeleton"
            style={{
              width: '100%',
              height: toPx(height, '40px'),
              borderRadius: 'var(--fqp-radius-xs)',
              marginBottom: i < count - 1 ? '8px' : 0,
              ...style,
            }}
          />,
        );
        break;

      case 'text':
      default:
        items.push(
          <div
            key={i}
            className="fqp-skeleton"
            style={{
              width: toPx(width, '60%'),
              height: toPx(height, '16px'),
              borderRadius: 'var(--fqp-radius-xs)',
              marginBottom: i < count - 1 ? '8px' : 0,
              ...style,
            }}
          />,
        );
        break;
    }
  }

  return <>{items}</>;
}
