/**
 * 법규 AI 채팅 시스템 React Context
 * API 클라이언트와 도메인 정보를 전역으로 관리
 */

import React, { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { getDomains as fetchDomains, healthCheck as checkHealth } from '../lib/law-api-client';
import type { DomainInfo } from '../lib/types';

/**
 * Context 타입 정의
 */
interface LawAPIContextType {
  /** 도메인 목록 */
  domains: DomainInfo[];

  /** 도메인 로딩 상태 */
  domainsLoading: boolean;

  /** 도메인 로딩 에러 */
  domainsError: string | null;

  /** 선택된 도메인 ID */
  selectedDomainId: string | null;

  /** 도메인 선택 */
  setSelectedDomainId: (domainId: string | null) => void;

  /** 도메인 목록 새로고침 */
  refreshDomains: () => Promise<void>;

  /** 백엔드 연결 상태 */
  isConnected: boolean;
}

/**
 * Context 생성
 */
const LawAPIContext = createContext<LawAPIContextType | undefined>(undefined);

/**
 * Provider Props
 */
interface LawAPIProviderProps {
  children: ReactNode;
}

/**
 * Law API Provider 컴포넌트
 *
 * @example
 * ```tsx
 * <LawAPIProvider>
 *   <LawChat />
 * </LawAPIProvider>
 * ```
 */
export function LawAPIProvider({ children }: LawAPIProviderProps) {
  const [domains, setDomains] = useState<DomainInfo[]>([]);
  const [domainsLoading, setDomainsLoading] = useState<boolean>(false);
  const [domainsError, setDomainsError] = useState<string | null>(null);
  const [selectedDomainId, setSelectedDomainId] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState<boolean>(false);

  /**
   * 도메인 목록 로드
   */
  const loadDomains = async () => {
    setDomainsLoading(true);
    setDomainsError(null);

    try {
      const domainList = await fetchDomains();
      setDomains(domainList);
      setDomainsError(null);
    } catch (error) {
      console.error('Failed to load domains:', error);
      setDomainsError(error instanceof Error ? error.message : 'Failed to load domains');
      setDomains([]);
    } finally {
      setDomainsLoading(false);
    }
  };

  /**
   * 백엔드 연결 확인
   */
  const checkConnection = async () => {
    try {
      await checkHealth();
      setIsConnected(true);
    } catch (error) {
      console.error('Backend connection failed:', error);
      setIsConnected(false);
    }
  };

  /**
   * 초기 로드
   */
  useEffect(() => {
    // 백엔드 연결 확인
    checkConnection();

    // 도메인 목록 로드
    loadDomains();

    // 주기적으로 연결 상태 확인 (30초마다)
    const interval = setInterval(checkConnection, 30000);

    return () => {
      clearInterval(interval);
    };
  }, []);

  /**
   * Context 값
   */
  const value: LawAPIContextType = {
    domains,
    domainsLoading,
    domainsError,
    selectedDomainId,
    setSelectedDomainId,
    refreshDomains: loadDomains,
    isConnected,
  };

  return <LawAPIContext.Provider value={value}>{children}</LawAPIContext.Provider>;
}

/**
 * Law API Context Hook
 *
 * @throws Context가 Provider 외부에서 사용된 경우
 *
 * @example
 * ```tsx
 * function MyComponent() {
 *   const { domains, selectedDomainId } = useLawAPI();
 *   // ...
 * }
 * ```
 */
export function useLawAPI(): LawAPIContextType {
  const context = useContext(LawAPIContext);

  if (context === undefined) {
    throw new Error('useLawAPI must be used within a LawAPIProvider');
  }

  return context;
}
