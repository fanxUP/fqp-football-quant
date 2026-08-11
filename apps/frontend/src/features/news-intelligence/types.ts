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
