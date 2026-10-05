import type { LandAnalysisResult } from '../../land-map/lib/types';

export interface LawArticle {
  hang_id: string;
  content: string;
  similarity: number;
  stages: string[];
  source: string;
  law_name?: string;
  law_type?: string;
  article?: string;
  unit_path?: string;
  via_a2a?: boolean;
  source_domain?: string;
  a2a_refined_query?: string;
}

export interface SearchStats {
  total: number;
  vector_count: number;
  relationship_count: number;
  graph_expansion_count: number;
  my_domain_count: number;
  neighbor_count?: number;
  a2a_collaboration_triggered?: boolean;
  a2a_collaborations?: number;
  a2a_results_count?: number;
}

export interface LawSearchResponse {
  results: LawArticle[];
  total_count?: number;
  query?: string;
  response_time?: number;
  stats?: SearchStats;
  domain_id?: string;
  domain_name?: string;
  domains_queried?: string[];
  a2a_domains?: string[];
}

export interface DomainInfo {
  domain_id: string;
  domain_name: string;
  node_count: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  search_response?: LawSearchResponse;
  land_analysis?: LandAnalysisResult;
  loading?: boolean;
  error?: string;
}

export interface LawSearchRequest {
  query: string;
  limit: number;
  domain_id?: string;
}

export interface ArticleHo {
  hang_number: string;
  number: string;
  content: string;
  full_id: string;
}

export interface ArticleHang {
  full_id: string;
  number: string;
  content: string;
  unit_path?: string;
  hos: ArticleHo[];
}

export interface ArticleJo {
  full_id: string;
  number: string;
  title?: string;
  content?: string;
  law_name?: string;
  unit_path?: string;
}

export interface ArticleDetail {
  jo_prefix: string;
  law_name: string;
  law_type: string;
  jo: ArticleJo | null;
  hangs: ArticleHang[];
  hang_count: number;
  ho_count: number;
}
