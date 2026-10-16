import { describe, expect, it } from 'vitest';
import type { Prediction } from '../../core/types';
import { comparisonReason, comparableRows } from './research';
export const prediction = (id=1, model_name='elo_rating'): Prediction => ({id,model_name,match_id:101,play_type:'spf',option_code:'3',predict_time:'2026-10-09T09:00:00',raw_model_probability:0,model_probability:0,feature_adjusted:false,market_probability:0,fair_odds:null,ev:-1,confidence:0,home_team:'甲',away_team:'乙',research_evidence:{model_version_id:id+10,model_version:'1.0',model_type:'statistical',feature_set_version:'v1',feature_snapshot_id:81,feature_snapshot_time:'2026-10-09T08:00:00',feature_version:'v1',feature_categories:['rest'],odds_snapshot_id:91,odds_snapshot_time:'2026-10-09T08:00:00'}});
describe('research comparison',()=>{
 it('compares exact evidence including genuine zero without ranking',()=>{const a=prediction(),b=prediction(2,'maher_poisson');expect(comparisonReason(a,b)).toBeNull();expect(comparableRows(a,[b,a])).toEqual([b,a]);});
 it.each([['match_id',102,'赛事'],['play_type','rqspf','玩法'],['option_code','h','选项'],['predict_time','2026-10-09T09:00:01','预测时刻']] as const)('rejects differing %s', (key,value,reason)=>{expect(comparisonReason(prediction(),{...prediction(2,'other'),[key]:value})).toContain(reason);});
 it.each([['feature_snapshot_id',82,'特征'],['odds_snapshot_id',92,'赔率']] as const)('rejects differing %s',(key,value,reason)=>{const b=prediction(2,'other');b.research_evidence![key]=value;expect(comparisonReason(prediction(),b)).toContain(reason);});
 it('does not invent missing legacy snapshots or version',()=>{const b=prediction(2,'other');delete b.research_evidence;expect(comparisonReason(prediction(),b)).toContain('证据缺失');expect(comparableRows(b,[b,prediction()])).toEqual([]);});
 it.each([null,NaN,1.1,-0.1])('refuses invalid probability %s',value=>{expect(comparisonReason(prediction(),{...prediction(2,'other'),model_probability:value})).toContain('概率');});
 it('rejects contradictory time and identifiers',()=>{const b=prediction(2,'other');b.research_evidence!.feature_snapshot_time='2026-10-09T10:00:00';expect(comparisonReason(prediction(),b)).toContain('快照');});
 it('refuses duplicate model outputs instead of silently choosing one',()=>{const a=prediction(),b=prediction(2,'other');expect(comparableRows(a,[a,b,{...a,id:3}])).toEqual([]);});
 it('does not count one model as a cross-model comparison',()=>{const a=prediction();expect(comparableRows(a,[a])).toEqual([]);});
});
