import type { ProviderId, ProviderStatus } from "../../shared/types";

interface Props {
  providers: ProviderStatus[];
  selectedProvider: ProviderId;
  onProviderChange(provider: ProviderId): void;
}

export function ProviderSwitch({
  providers,
  selectedProvider,
  onProviderChange
}: Props) {
  return (
    <div className="provider-switch" aria-label="AI provider">
      {(["codex", "claude"] as const).map((providerId) => {
        const status = providers.find((provider) => provider.id === providerId);
        return (
          <button
            className={selectedProvider === providerId ? "active" : ""}
            disabled={!status?.authenticated}
            key={providerId}
            onClick={() => onProviderChange(providerId)}
            title={status?.detail ?? "상태 확인 중"}
          >
            <i className={status?.authenticated ? "online" : ""} />
            {providerId === "codex" ? "GPT" : "Claude"}
          </button>
        );
      })}
    </div>
  );
}
