import { MessageSquare, MessageSquarePlus } from "lucide-react";

import "./styles.css";

export interface SessionNavigationItem {
  id: string;
  provider: string;
  title: string;
  updatedAt: string;
}

interface Props {
  activeSessionId: string | null;
  onNewSession(): void;
  onSelectSession(id: string): void;
  query: string;
  sessions: readonly SessionNavigationItem[];
}

export function SessionNavigator({ activeSessionId, onNewSession, onSelectSession, query, sessions }: Props) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleSessions = sessions.filter((session) => session.title.toLocaleLowerCase().includes(normalizedQuery));
  const groups = groupSessions(visibleSessions);

  return (
    <section aria-label="Sessions" className="session-navigation" role="region">
      <div className="session-navigation-actions"><button onClick={onNewSession}><MessageSquarePlus size={15} />New session</button></div>
      <div className="session-navigation-scroll">
        {groups.map(([label, items]) => <div className="session-group" key={label}>
          <h2>{label}</h2>
          {items.map((session) => <button
            aria-current={session.id === activeSessionId ? "page" : undefined}
            className={`session-navigation-row ${session.id === activeSessionId ? "active" : ""}`}
            key={session.id}
            onClick={() => onSelectSession(session.id)}
          >
            <MessageSquare size={13} /><span><strong title={session.title}>{session.title}</strong><small>{session.provider} · local session</small></span>
          </button>)}
        </div>)}
        {visibleSessions.length === 0 && <div className="session-navigation-empty">No sessions found.</div>}
      </div>
    </section>
  );
}

function groupSessions(sessions: readonly SessionNavigationItem[]): Array<[string, readonly SessionNavigationItem[]]> {
  const today = new Date().toDateString();
  const recent = sessions.filter((session) => new Date(session.updatedAt).toDateString() === today);
  const earlier = sessions.filter((session) => new Date(session.updatedAt).toDateString() !== today);
  const groups: Array<[string, readonly SessionNavigationItem[]]> = [["Today", recent], ["Earlier", earlier]];
  return groups.filter(([, items]) => items.length > 0);
}
