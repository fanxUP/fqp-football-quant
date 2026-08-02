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
  const [showAll, setShowAll] = useState(true);
  const [expandedLeagues, setExpandedLeagues] = useState<Set<string>>(
    () => new Set(),
  );

  useEffect(() => {
    setExpandedLeagues((current) => {
      const available = new Set(leagueNames);
      const retained = new Set(Array.from(current).filter((leagueName) => available.has(leagueName)));
      // all leagues collapsed by default
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
          <button type="button" className="fqp-btn" onClick={() => { setExpandedLeagues(new Set(leagueNames)); setShowAll(true); }}>全部展开</button>
          <button type="button" className="fqp-btn" onClick={() => { setExpandedLeagues(new Set()); setShowAll(false); }}>全部收起</button>
        </div>
      </header>

      {/* 全部冷门 — flat list of all matches */}
      <section className="upset-league-group">
        <h3>
          <button
            type="button"
            className="upset-league-toggle"
            aria-label="全部冷门"
            aria-expanded={showAll}
            aria-controls="upset-league-all"
            onClick={() => setShowAll((v) => !v)}
          >
            <span className="upset-league-chevron" aria-hidden="true">›</span>
            <span>全部冷门</span>
            <strong>{items.length} 场</strong>
          </button>
        </h3>
        {showAll && (
          <div id="upset-league-all" className="upset-league-panel upset-all-panel">
            {items.map((item) => (
              <UpsetCard key={item.id} item={item} onOpen={() => onOpen(item.id)} />
            ))}
          </div>
        )}
      </section>

      <hr className="upset-section-divider" />

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
