export type NewsSourceLevel = 'S' | 'A' | 'B' | 'C' | 'D';

export interface NewsIntelligenceOverview {
  articleCount: number;
  linkedMatchCount: number;
  sourceCount: number;
  healthySourceCount: number;
  lastCapturedAt: string | null;
  productionFeatureEnabled: boolean;
}

export interface NewsArticleItem {
  id: number;
  matchId: number | null;
  officialMatchCode: string | null;
  leagueName?: string | null;
  homeTeamName?: string | null;
  awayTeamName?: string | null;
  sourceName: string;
  sourceLevel: NewsSourceLevel;
  sourceType?: string;
  title: string;
  description?: string | null;
  canonicalUrl: string;
  language?: string | null;
  publishedAt: string;
  observedAt?: string;
  capturedAt?: string;
  availableAt: string;
}

export interface NewsSourceItem {
  id: number;
  sourceCode: string;
  sourceName: string;
  publisherDomain?: string | null;
  sourceLevel: NewsSourceLevel;
  sourceType?: string;
  defaultLanguage?: string | null;
  enabled: boolean;
  lastSuccessAt: string | null;
  lastError: string | null;
}

export type NewsEventVerificationStatus = 'pending' | 'verified' | 'rejected' | 'conflicting';

export interface NewsEventItem {
  id: number;
  eventType: string;
  direction: 'positive' | 'negative' | 'neutral' | 'mixed';
  title: string;
  summary: string;
  severityScore: number;
  confidenceScore: number;
  matchRelevanceScore: number;
  verificationStatus: NewsEventVerificationStatus;
  occurredAt: string | null;
  firstAvailableAt: string;
  extractionMethod: string;
  extractionVersion: string;
  matchId: number | null;
  officialMatchCode: string | null;
  leagueName: string | null;
  homeTeamName: string | null;
  awayTeamName: string | null;
  sourceCount: number;
}

export interface NewsFeatureSnapshotItem {
  snapshotId: number;
  matchId: number;
  officialMatchCode: string;
  leagueName: string | null;
  homeTeamName: string;
  awayTeamName: string;
  snapshotLabel: 'T24H' | 'T6H' | 'T90M' | 'T45M' | 'POST120';
  snapshotCutoff: string;
  homeNetImpact: number;
  awayNetImpact: number;
  verifiedEventCount: number;
  pendingEventCount: number;
  evidenceCount: number;
  coverageScore: number;
  confidenceScore: number;
  featureVersion: string;
}

export interface NewsShadowModelMetric {
  modelName: string;
  modelVersion: string;
  shadowVersion: string;
  sampleSize: number;
  baselineBrier: number | null;
  shadowBrier: number | null;
  brierDelta: number | null;
  baselineLogLoss: number | null;
  shadowLogLoss: number | null;
}

export interface NewsShadowExperiment {
  sampleSize: number;
  baselineBrier: number | null;
  shadowBrier: number | null;
  brierDelta: number | null;
  baselineLogLoss: number | null;
  shadowLogLoss: number | null;
  logLossDelta: number | null;
  productionFeatureEnabled: boolean;
  models: NewsShadowModelMetric[];
}

export interface NewsReleaseState {
  mode: 'shadow' | 'production';
  approvedShadowVersion: string | null;
  approvedFeatureVersion: string | null;
  approvalNote: string | null;
  approvedBy: string | null;
  approvedAt: string | null;
  updatedAt: string | null;
  candidateShadowVersion: string;
  candidateFeatureVersion: string;
  metrics: {
    sampleSize: number;
    brierDelta: number | null;
    logLossDelta: number | null;
  };
  promotion: {
    eligible: boolean;
    reason: string;
  };
}
