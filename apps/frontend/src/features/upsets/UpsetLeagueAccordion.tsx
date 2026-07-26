import { useEffect, useMemo, useState } from 'react';
import type { UpsetListItem } from './types';
import { UpsetCard } from './UpsetOverview';

interface UpsetLeagueAccordionProps {
  items: UpsetListItem[];
  onOpen: (eventId: number) => void;
}

interface LeagueGroup {
  leagueName: string;
  items: UpsetListItem[];
}

function groupByLeague(items: UpsetListItem[]): LeagueGroup[] {
  const groups = new Map<string, UpsetListItem[]>();
  items.forEach((item) => {
    const leagueName = item.league_name || '其他联赛';
    groups.set(leagueName, [...(groups.get(leagueName) ?? []), item]);
  });
  return Array.from(groups, ([leagueName, leagueItems]) => ({ leagueName, items: leagueItems }));
}

export default function UpsetLeagueAccordion({ items, onOpen }: UpsetLeagueAccordionProps) {
  const groups = useMemo(() => groupByLeague(items), [items]);
  const leagueNames = useMemo(() => groups.map((group) => group.leagueName), [groups]);
  const [expandedLeagues, setExpandedLeagues] = useState<Set<string>>(
    () => new Set(groups[0] ? [groups[0].leagueName] : []),
  );

  useEffect(() => {
    setExpandedLeagues((current) => {
      const available = new Set(leagueNames);
      const retained = new Set(Array.from(current).filter((leagueName) => available.has(leagueName)));
      if (retained.size === 0 && leagueNames[0]) retained.add(leagueNames[0]);
      return retained;
    });
  }, [leagueNames]);

  const toggleLeague = (leagueName: string) => {
    setExpandedLeagues((current) => {
      const next = new Set(current);
      if (next.has(leagueName)) next.delete(leagueName);
      else next.add(leagueName);
      return next;
    });
  };

  return (
    <section className="upset-league-accordion" aria-label="按联赛折叠的冷门比赛">
      <header className="upset-league-accordion-toolbar">
        <div>
          <h2>联赛导航</h2>
          <span>{groups.length} 个联赛 · {items.length} 场冷门</span>
        </div>
        <div className="upset-league-accordion-actions">
          <button type="button" className="fqp-btn" onClick={() => setExpandedLeagues(new Set(leagueNames))}>全部展开</button>
          <button type="button" className="fqp-btn" onClick={() => setExpandedLeagues(new Set())}>全部收起</button>
        </div>
      </header>

      <div className="upset-league-groups">
        {groups.map((group) => {
          const expanded = expandedLeagues.has(group.leagueName);
          const panelId = `upset-league-${encodeURIComponent(group.leagueName)}`;
          return (
            <section className="upset-league-group" key={group.leagueName}>
              <h3>
                <button
                  type="button"
                  className="upset-league-toggle"
                  aria-label={`${group.leagueName}，${group.items.length}场`}
                  aria-expanded={expanded}
                  aria-controls={panelId}
                  onClick={() => toggleLeague(group.leagueName)}
                >
                  <span className="upset-league-chevron" aria-hidden="true">›</span>
                  <span>{group.leagueName}</span>
                  <strong>{group.items.length} 场</strong>
                </button>
              </h3>
              {expanded && (
                <div id={panelId} className="upset-league-panel">
                  {group.items.map((item) => (
                    <UpsetCard key={item.id} item={item} onOpen={() => onOpen(item.id)} />
                  ))}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </section>
  );
}
