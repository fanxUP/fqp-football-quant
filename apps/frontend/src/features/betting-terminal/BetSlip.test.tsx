import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BetSlip from './BetSlip';

describe('BetSlip', () => {
  it('将比分玩法的内部选项代码显示为中文', () => {
    render(<BetSlip
      selections={[{
        match_id: 1, home_team: '主队', away_team: '客队', league_name: '测试联赛', kickoff_time: '2026-08-03T20:00:00',
        play_type: 'bf', play_type_label: '比分', option_code: 'other_h', option_name: 'other_h', sp_value: 9.9, is_dan: false,
      }]}
      selectedMatchCount={1}
      selectedPassTypes={['single']}
      availablePassTypes={['single']}
      multiple={1}
      calculation={{ pass_type: 'single', multiple: 1, bet_count: 1, total_cost: 2, max_prize: 19.8, match_count: 1, combinations: [], available_pass_types: ['single'] }}
      calculating={false}
      submitting={false}
      warning=""
        detailsOpen
      onTogglePassType={vi.fn()}
      onMultiple={vi.fn()}
      onToggleDetails={vi.fn()}
      onConfirm={vi.fn()}
    />);

    expect(screen.getByText('胜其他 @9.90')).toBeInTheDocument();
    expect(screen.queryByText('other_h @9.90')).not.toBeInTheDocument();
  });
});
