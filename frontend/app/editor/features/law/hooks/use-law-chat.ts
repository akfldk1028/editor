/**
 * 법규 AI 채팅 커스텀 훅
 * 메시지 관리, 검색 요청, 상태 관리
 */

import { useState, useCallback, useRef } from 'react';
import { useLawAPI } from '../contexts/LawAPIContext';
import { search as lawSearch, searchInDomain } from '../lib/law-api-client';
import type { ChatMessage, LawSearchRequest } from '../lib/types';

/**
 * 채팅 훅 반환 타입
 */
export interface UseLawChatReturn {
  /** 채팅 메시지 목록 */
  messages: ChatMessage[];

  /** 현재 로딩 중인지 여부 */
  isLoading: boolean;

  /** 검색 실행 */
  search: (query: string, limit?: number) => Promise<void>;

  /** 메시지 추가 */
  addMessage: (message: Omit<ChatMessage, 'id' | 'timestamp'>) => void;

  /** 메시지 초기화 */
  clearMessages: () => void;

  /** 마지막 메시지 제거 */
  removeLastMessage: () => void;
}

/**
 * 법규 AI 채팅 훅
 *
 * @example
 * ```tsx
 * function ChatComponent() {
 *   const { messages, isLoading, search } = useLawChat();
 *
 *   const handleSearch = async () => {
 *     await search("개발행위 허가 요건");
 *   };
 *
 *   return (
 *     <div>
 *       {messages.map(msg => <div key={msg.id}>{msg.content}</div>)}
 *     </div>
 *   );
 * }
 * ```
 */
export function useLawChat(): UseLawChatReturn {
  const { selectedDomainId } = useLawAPI();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const messageIdCounter = useRef(0);

  /**
   * 고유 메시지 ID 생성
   */
  const generateMessageId = useCallback(() => {
    messageIdCounter.current += 1;
    return `msg_${Date.now()}_${messageIdCounter.current}`;
  }, []);

  /**
   * 메시지 추가
   */
  const addMessage = useCallback(
    (message: Omit<ChatMessage, 'id' | 'timestamp'>) => {
      const newMessage: ChatMessage = {
        ...message,
        id: generateMessageId(),
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, newMessage]);
    },
    [generateMessageId]
  );

  /**
   * 법규 검색 실행
   */
  const search = useCallback(
    async (query: string, limit: number = 10) => {
      if (!query.trim()) {
        return;
      }

      // 사용자 메시지 추가
      addMessage({
        role: 'user',
        content: query,
      });

      // 로딩 메시지 추가
      const loadingMessage: ChatMessage = {
        id: generateMessageId(),
        role: 'assistant',
        content: '검색 중...',
        loading: true,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, loadingMessage]);
      setIsLoading(true);

      try {
        // 검색 요청 생성
        const request: LawSearchRequest = {
          query,
          limit,
          domain_id: selectedDomainId || undefined,
        };

        // API 호출
        const startTime = Date.now();
        let response;

        if (selectedDomainId) {
          // 특정 도메인 검색
          response = await searchInDomain(selectedDomainId, request);
        } else {
          // 자동 라우팅 검색
          response = await lawSearch(request);
        }

        const responseTime = Date.now() - startTime;
        response.response_time = responseTime;

        // 로딩 메시지를 결과 메시지로 교체
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === loadingMessage.id
              ? {
                  ...msg,
                  content: `검색 완료 (${responseTime}ms)`,
                  search_response: response,
                  loading: false,
                }
              : msg
          )
        );
      } catch (error) {
        console.error('Search failed:', error);

        // 로딩 메시지를 에러 메시지로 교체
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === loadingMessage.id
              ? {
                  ...msg,
                  content: '검색에 실패했습니다.',
                  error: error instanceof Error ? error.message : 'Unknown error',
                  loading: false,
                }
              : msg
          )
        );
      } finally {
        setIsLoading(false);
      }
    },
    [selectedDomainId, addMessage, generateMessageId]
  );

  /**
   * 메시지 초기화
   */
  const clearMessages = useCallback(() => {
    setMessages([]);
    messageIdCounter.current = 0;
  }, []);

  /**
   * 마지막 메시지 제거
   */
  const removeLastMessage = useCallback(() => {
    setMessages((prev) => prev.slice(0, -1));
  }, []);

  return {
    messages,
    isLoading,
    search,
    addMessage,
    clearMessages,
    removeLastMessage,
  };
}
