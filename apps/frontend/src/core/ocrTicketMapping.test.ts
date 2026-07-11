import { describe, expect, it } from 'vitest';
import type { BettingMatch, TicketOcrResult } from './types';
import { mapOcrTicketToSlip } from './ocrTicketMapping';

function match(overrides: Partial<BettingMatch> = {}): BettingMatch {
  return {
    match_id: overrides.match_id ?? 1001,
    business_date: '2026-07-07',
    league_name: '日职联',
    home_team_name: '东京FC',
    away_team_name: '大阪钢巴',
    kickoff_time: '2026-07-07T18:00:00',
    match_status: 'sale',
    match_num_str: overrides.match_num_str ?? '周二001',
    odds: overrides.odds ?? {
      spf: {
        options: [
          { option_code: '3', option_name: '胜', sp_value: 1.82 },
          { option_code: '1', option_name: '平', sp_value: 3.2 },
        ],
      },
      rqspf: { handicap: -1, options: [{ option_code: '0', option_name: '让负', sp_value: 2.05 }] },
      zjq: { options: [] },
      bf: { options: [] },
      bqc: { options: [] },
    },
  };
}

describe('mapOcrTicketToSlip', () => {
  it('maps OCR items to bet slip selections by official match code and option', () => {
    const ocr: TicketOcrResult = {
      success: true,
      items: [{ match_code: '001', play_type: 'spf', option_code: '3', option_name: '胜', sp_value: 1.8 }],
    };

    const result = mapOcrTicketToSlip(ocr, [match()]);

    expect(result.mapped).toHaveLength(1);
    expect(result.mapped[0]).toMatchObject({
      match_id: 1001,
      home_team: '东京FC',
      away_team: '大阪钢巴',
      play_type: 'spf',
      play_type_label: '胜平负',
      option_code: '3',
      option_name: '主胜',
      sp_value: 1.82,
    });
    expect(result.unmatched).toEqual([]);
  });

  it('keeps OCR items unmatched when match or option cannot be proven', () => {
    const ocr: TicketOcrResult = {
      success: true,
      items: [
        { match_code: '999', play_type: 'spf', option_code: '3', option_name: '胜', sp_value: 1.8 },
        { match_code: '001', play_type: 'spf', option_code: '0', option_name: '负', sp_value: 4.1 },
      ],
    };

    const result = mapOcrTicketToSlip(ocr, [match()]);

    expect(result.mapped).toEqual([]);
    expect(result.unmatched).toEqual([
      { label: '999 spf 胜', reason: '未找到对应在售比赛' },
      { label: '001 spf 负', reason: '未找到对应选项' },
    ]);
  });
});
