# DWG Intelligence UI captures

현재 프런트엔드는 React Router가 없는 단일 SPA이며 실제 URL 라우트는 `/` 하나다.
확인하기 쉽도록 주요 상태를 1440×900으로 캡처하고 한 장의 overview로 묶었다.

![UI overview](./00-overview.png)

| 상태 | 캡처 |
|---|---|
| 기본 워크스페이스 | [01-workspace-loaded.png](./01-workspace-loaded.png) |
| 실제 검사 완료 | [02-inspection-complete.png](./02-inspection-complete.png) |
| 레이어 0 숨김 | [03-layer-hidden.png](./03-layer-hidden.png) |
| Claude 선택 | [04-claude-selected.png](./04-claude-selected.png) |

재생성:

```powershell
Set-Location C:\DK\DWG\frontend
npm run capture:docs
```
