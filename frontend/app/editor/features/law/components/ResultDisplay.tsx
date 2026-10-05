import React, { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { LawSearchResponse, LawArticle } from '../lib/types';
import { LawArticleCard } from './LawArticleCard';
import { StatsPanel } from './StatsPanel';

interface ResultDisplayProps {
  response: LawSearchResponse;
  selectedArticle?: LawArticle | null;
  onSelectArticle?: (article: LawArticle) => void;
}

export function ResultDisplay({ response, selectedArticle, onSelectArticle }: ResultDisplayProps) {
  const { results, stats, domain_name, response_time, domains_queried, a2a_domains } = response;

  const hasA2A = stats?.a2a_collaboration_triggered && a2a_domains && a2a_domains.length > 0;
  const [selfResults, a2aResults] = useMemo(
    () => [results.filter((r) => !r.via_a2a), results.filter((r) => r.via_a2a)],
    [results]
  );

  if (results.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <StatsPanel stats={stats} responseTime={response_time} domainName={domain_name} a2aDomains={a2a_domains} />
        <div style={{ padding: '48px 0', textAlign: 'center' }}>
          <p style={{ fontSize: 14, color: '#64748b' }}>검색 결과가 없습니다</p>
          <p style={{ fontSize: 13, color: '#475569', marginTop: 4 }}>다른 검색어를 시도해 보세요</p>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <StatsPanel stats={stats} responseTime={response_time} domainName={domain_name} a2aDomains={a2a_domains} />

      {hasA2A ? (
        <>
          {selfResults.length > 0 && (
            <CardList results={selfResults} startIndex={1} selectedArticle={selectedArticle} onSelectArticle={onSelectArticle} />
          )}
          {a2aResults.length > 0 && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '4px 0' }}>
                <span style={{ height: 1, flex: 1, background: 'rgba(255,255,255,0.04)' }} />
                <span style={{ fontSize: 11, color: '#475569', fontWeight: 500 }}>
                  A2A &middot; {a2a_domains?.length || 0}개 도메인
                </span>
                <span style={{ height: 1, flex: 1, background: 'rgba(255,255,255,0.04)' }} />
              </div>
              <CardList results={a2aResults} startIndex={selfResults.length + 1} selectedArticle={selectedArticle} onSelectArticle={onSelectArticle} />
            </>
          )}
        </>
      ) : (
        <CardList results={results} startIndex={1} selectedArticle={selectedArticle} onSelectArticle={onSelectArticle} />
      )}
    </div>
  );
}

const CardList = React.memo(function CardList({ results, startIndex, selectedArticle, onSelectArticle }: {
  results: LawArticle[]; startIndex: number;
  selectedArticle?: LawArticle | null;
  onSelectArticle?: (article: LawArticle) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <AnimatePresence mode="popLayout">
        {results.map((article, i) => (
          <motion.div
            key={article.hang_id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, delay: i * 0.03 }}
          >
            <LawArticleCard
              article={article}
              index={startIndex + i}
              selected={selectedArticle?.hang_id === article.hang_id}
              onSelect={onSelectArticle}
            />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
});
