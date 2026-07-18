import type { BettingOddsOption } from '../../core/types';
import { arrangeScoreOdds } from './scoreOddsLayout';

interface ScoreOddsGridProps {
  options: ReadonlyArray<BettingOddsOption>;
  selectedOptionCodes: ReadonlySet<string>;
  selectable: boolean;
  onToggle: (option: BettingOddsOption) => void;
}

export default function ScoreOddsGrid({
  options,
  selectedOptionCodes,
  selectable,
  onToggle,
}: ScoreOddsGridProps) {
  return (
    <div className="sporttery-score-grid" role="group" aria-label="比分选项">
      {arrangeScoreOdds(options).map(({ option, label, isWide }) => {
        const selected = selectedOptionCodes.has(option.option_code);
        return (
          <button
            key={option.option_code}
            type="button"
            className={`sporttery-modal-odd ${isWide ? 'is-score-wide' : ''} ${selected ? 'is-selected' : ''}`.trim()}
            aria-label={`比分 ${label} ${option.sp_value.toFixed(2)}`}
            aria-pressed={selected}
            disabled={!selectable}
            onClick={() => onToggle(option)}
          >
            <span>{label}</span>
            <small>{option.sp_value.toFixed(2)}</small>
          </button>
        );
      })}
    </div>
  );
}
