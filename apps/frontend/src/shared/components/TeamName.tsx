import type { CSSProperties } from 'react';
import TeamLogo from './TeamLogo';

interface TeamNameProps {
  name: string;
  size?: number;
  style?: CSSProperties;
}

/** A consistent, accessible team crest plus name treatment for match UIs. */
export default function TeamName({ name, size = 20, style }: TeamNameProps) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0, ...style }}>
      <TeamLogo nameCn={name} size={size} />
      <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
    </span>
  );
}
