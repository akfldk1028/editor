import { AnimatePresence, motion } from 'framer-motion'
import React from 'react'
import LandAnalysisPanel from '../../land-map/components/LandAnalysisPanel'
import type { SearchProgress } from '../hooks/use-law-search-stream'
import type { ChatMessage, LawArticle } from '../lib/types'
import { ResultDisplay } from './ResultDisplay'
import {
  SearchCompleteHeader,
  SearchErrorIndicator,
  SearchProgressIndicator,
} from './SearchProgress'

// ─────────────────────────────────────────────────────────────────────────────
// MessageList — 채팅 메시지 목록 + SSE 진행률
// ─────────────────────────────────────────────────────────────────────────────

export const MessageList = React.memo(function MessageList({
  messages,
  streamingMode,
  isSearching,
  progress,
  selectedArticle,
  onSelectArticle,
  messagesEndRef,
}: {
  messages: ChatMessage[]
  streamingMode: boolean
  isSearching: boolean
  progress: SearchProgress | null
  selectedArticle: LawArticle | null
  onSelectArticle: (a: LawArticle | null) => void
  messagesEndRef: React.RefObject<HTMLDivElement | null>
}) {
  return (
    <div style={{ flex: 1, overflowY: 'auto' }}>
      <div style={{ maxWidth: 860, margin: '0 auto', padding: '24px 24px 32px' }}>
        <AnimatePresence mode="popLayout">
          {messages.map((message) => (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.25 }}
              style={{ marginBottom: 20 }}
            >
              {message.role === 'user' && (
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <div
                    style={{
                      maxWidth: '70%',
                      padding: '10px 16px',
                      borderRadius: 12,
                      background: 'rgba(99,102,241,0.12)',
                      border: '1px solid rgba(99,102,241,0.15)',
                      color: '#e2e8f0',
                      fontSize: 14,
                      fontWeight: 500,
                    }}
                  >
                    {message.content}
                  </div>
                </div>
              )}
              {message.role === 'assistant' && (
                <div style={{ width: '100%' }}>
                  {message.loading && (
                    <div
                      style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 0' }}
                    >
                      {[0, 1, 2].map((i) => (
                        <div
                          key={i}
                          style={{
                            height: i === 0 ? 16 : 12,
                            width: i === 2 ? '60%' : '100%',
                            borderRadius: 4,
                            background:
                              'linear-gradient(90deg, rgba(255,255,255,0.02) 25%, rgba(255,255,255,0.05) 50%, rgba(255,255,255,0.02) 75%)',
                            backgroundSize: '200% 100%',
                            animation: 'shimmer 1.5s linear infinite',
                            animationDelay: `${i * 0.1}s`,
                          }}
                        />
                      ))}
                      <span style={{ fontSize: 12, color: '#334155', marginTop: 4 }}>
                        {message.content}
                      </span>
                    </div>
                  )}
                  {message.error && !message.loading && (
                    <SearchErrorIndicator message={message.error} />
                  )}
                  {message.land_analysis && !message.loading && !message.error && (
                    <LandAnalysisPanel
                      analysis={message.land_analysis}
                      address={message.content}
                      onSelectArticle={(a) =>
                        onSelectArticle({
                          hang_id: a.hang_id,
                          content: a.content,
                          similarity: a.similarity || 0,
                          stages: a.stages || [],
                          source: 'land',
                          law_name: a.law_name,
                          law_type: a.law_type,
                          article: a.article,
                        })
                      }
                    />
                  )}
                  {message.search_response && !message.loading && !message.error && (
                    <div>
                      <div style={{ marginBottom: 8 }}>
                        <SearchCompleteHeader
                          resultCount={
                            message.search_response.total_count ||
                            message.search_response.results.length
                          }
                          responseTime={message.search_response.response_time || 0}
                          domainName={message.search_response.domain_name}
                        />
                      </div>
                      <ResultDisplay
                        response={message.search_response}
                        selectedArticle={selectedArticle}
                        onSelectArticle={onSelectArticle}
                      />
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {/* SSE 스트리밍 진행률 */}
        {streamingMode && isSearching && progress && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            style={{
              padding: 20,
              borderRadius: 20,
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid rgba(255,255,255,0.06)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
            }}
          >
            {progress.status !== 'complete' && progress.status !== 'error' && (
              <SearchProgressIndicator progress={progress} />
            )}
            {progress.status === 'error' && (
              <SearchErrorIndicator message={progress.message || '알 수 없는 오류'} />
            )}
            {progress.status === 'complete' && (
              <SearchCompleteHeader
                resultCount={progress.result_count || 0}
                responseTime={progress.response_time || 0}
                domainName={progress.domain_name}
              />
            )}
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>
    </div>
  )
})
