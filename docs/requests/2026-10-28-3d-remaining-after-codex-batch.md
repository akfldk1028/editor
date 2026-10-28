# 3D 주변 건물 — Codex 10-26 묶음 뒤 남은 것 (크롬 실측 2026-10-28 15:5x)

## 고쳐진 것 (측정)
- 메인 스레드 막힘: 가까이 0 ms/10 s, 넓게 0 ms/8 s (전엔 탭 멈춤).
- `world-buildings/catalog.json` 19.3 MB 통째 받기 사라짐.
- 회색/흰색 얼룩·타일 경계 사라짐, 카메라가 대지를 잡음, 대화 배치안이 3D에 그려짐.

## 남은 것
1. **넓게 보면 건물 빈 구역** (스크린샷 `claude-chrome-screenshots-NzbkDl/screenshot-1793170548477-2.jpg` 왼쪽 상단: 바탕지도 2D 윤곽만).
   상태줄: `주변 신축 보강 실패: signal timed out`. 보강(supplement) 요청이 시간 초과되면 그 칸이 비고 2D 윤곽이 드러남.
   → 시간 초과 시 빈 칸으로 두지 말 것: 미리 구운 메시 또는 상위 레벨 타일로 채우고, 3D 모드에서는 바탕지도 건물 레이어를 숨길 것.
2. **단일 출처는 게이트만 있음.** `world-building-renderer.ts`는 `ace-map-release-v2` + 전국 coverage 완료(`missingRegions 0`)일 때만 `national-prebuilt`로 감.
   지금 서비스 release는 `ace-map-release-v1`, coverage `complete:false` (`missingPreparedTiles 679`, `partialCoordinates 113`) → 여전히 `legacy-hybrid`(미리 구운 메시 + PMTiles supplement) 혼합.
   → v2 전국 publication을 만들어 전환하거나, 그 전까지 legacy-hybrid에서도 같은 재질·같은 높이 규칙으로 그리도록 할 것(빈 칸 0).
3. 측정으로 보고: 684-1 근·중·원 3거리 스크린샷 + 빈 타일 수 0 확인.

## 손대지 말 것
- `building-tiles.ts`의 postUpdate 빈도 제한(`4948eb1c`), 사용자 줌 유지(`00dd0a7a`).
