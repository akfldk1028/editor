import { Bot } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * An OAuth CLI provider answers through a spawned process and routinely takes
 * about a minute. Without a visible pending state the transcript is unchanged
 * for that whole time and reads as a request that never arrived, so the wait
 * is shown and counted.
 */
export function PendingResponse({ onCancel }: { onCancel(): void }) {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      1000
    );
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="message agent-message pending-response" data-testid="pending-response">
      <div className="message-label"><Bot size={12} /> ASSISTANT</div>
      <p aria-live="polite" role="status">
        <span className="pending-dots" aria-hidden="true"><i /><i /><i /></span>
        응답 생성 중… {formatElapsed(seconds)}
      </p>
      <p className="pending-note">
        로컬 OAuth CLI가 답하는 동안 보통 1분쯤 걸립니다.
      </p>
      <button className="pending-cancel" onClick={onCancel} type="button">중단</button>
    </div>
  );
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}초`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}분 ${seconds % 60}초`;
}
