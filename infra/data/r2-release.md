# 검증된 지도 릴리스의 R2 이전

현재 지원: `ace-map-release-v1`, `ace-map-release-v2`(NGII 전국 HLOD). 원본·로컬 릴리스는 수정하거나 삭제하지 않습니다.

저장소 루트에서 키 없이 검사:

```powershell
C:/Python313/python.exe -X utf8 infra/data/r2_release.py --data-root C:/Data/25_ACE --release-id <sealed-id> --dry-run
```

`release_store.verify`와 봉인된 `management/releases/<id>/files.jsonl`을 사용합니다. v1 업로드 대상은 건물 PMTiles/manifest, 지역 메시·공간 카탈로그, 지형 PMTiles뿐입니다. management, 영수증, 키, 환경파일, 원본은 공개 대상에서 제외됩니다. dry-run은 네트워크를 호출하지 않습니다.

서비스 검증이 끝난 뒤 사용자가 git 제외 `.env.r2.local`의 `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`을 직접 설정합니다. 실제 업로드 실행에는 Python 환경의 boto3가 필요합니다.

```powershell
C:/Python313/python.exe -X utf8 infra/data/r2_release.py --data-root C:/Data/25_ACE --release-id <sealed-id> --env-file .env.r2.local --upload --workers 4 --retries 2
```

이 문서를 작성하면서 실제 업로드는 실행하지 않았습니다. 기본 동시 파일 4개, 최대8개이며 각 multipart 작업은 내부 병렬화를 끕니다. 모든 파일의 크기/SHA256을 로컬 및 원격 GET 스트림으로 대조합니다. 재개도 원격 GET을 다시 검증합니다. 다른 내용의 기존 immutable 객체는 덮어쓰지 않으며, 이 실행이 기록한 실패 업로드만 재전송합니다. 비공개 영수증·intent는 `DATA_ROOT/management/r2/<sealed-id>/`에 남습니다.

원래 로컬 ID는 `sourceReleaseId`로 보존합니다. `assetBases`, 공개 전송 목록의 hash/count를 포함한 원격 body의 정규 JSON SHA256을 새 `releaseId`로 사용합니다. 원본 manifest는 바꾸지 않습니다. 객체 검증 완료 후 원격 immutable manifest, Scene `tiles/buildings/latest.json`, 편집기 `releases/current.json` 순서로 발행합니다. 마지막 두 포인터는 서로 다른 객체라 원자적 동시 전환은 아닙니다. 편집기는 하나의 current snapshot으로 건물·지형을 고정합니다.

편집기는 `NEXT_PUBLIC_MAP_RELEASE_URL=<public-base>/releases/current.json`, Scene은 `SCENE_BUILDINGS_BASE_URL=<public-base>/tiles/buildings`를 사용합니다. 개별 NEXT_PUBLIC_*_BASE_URL override가 남으면 우선 적용되므로 전환 시 일관성을 확인해야 합니다. public base는 접근 가능한 커스텀 도메인 또는 r2.dev 주소이며 버킷 생성·공개 설정은 이 도구가 수행하지 않습니다.

버전 객체: `public, max-age=31536000, immutable`. latest/current: 60초. 범위 요청·브라우저 CORS·첫 로딩 실측은 업로드 후 별도 서비스 확인이 필요합니다.

CORS 변경은 별도 명시 옵션에서만 수행합니다. 기존 버킷 CORS 전체 규칙을 아래 읽기 규칙으로 교체하므로 공유 버킷은 기존 규칙을 먼저 검토해야 합니다.

```powershell
# 위 --upload 명령에 필요할 때만 추가
--configure-cors --origin http://127.0.0.1:3003 --origin https://editor.example.com
```

GET/HEAD, 요청 헤더 Range/If-Match/If-None-Match/If-Range, 노출 헤더 Content-Range/ETag/Content-Length/Accept-Ranges를 사용합니다. 근거: [Cloudflare R2 CORS 공식 문서](https://developers.cloudflare.com/r2/buckets/cors/). 허용 origin을 생략하면 변경하지 않고 실패합니다.

## v2 (전국 NGII 릴리스)

공개 대상은 Cesium이 실제로 받는 것뿐입니다: 지형 PMTiles(`world-terrain/*.pmtiles`), 전국 HLOD `world-buildings/national/<hash>/`의 `tileset.json`·`nodes/*.json`·`nodes/*.b3dm.gz`, 지역 폴더 `world-buildings/national-regions-gzip-v2/<id>/`의 `tileset.json`·`*.b3dm.gz`. `summaries/`, `candidate-inputs.json`, `candidate-receipt.json`, `footprints.json.gz`, `ground-source.json.gz`, management 증거는 비공개입니다(`national-buildings.ts`는 tileset 하나만 열고, 나머지는 굽기·검증 도구만 읽습니다).

`.b3dm.gz`는 로컬 `/api/map-data/`(`lib/prepared-map-files.ts`)와 같은 표현으로 올립니다: 같은 키, gzip 바이트 그대로, `Content-Encoding: gzip`, `Content-Type: application/octet-stream`. 브라우저가 풀어 Cesium에 b3dm을 넘기므로 이 헤더가 없으면 타일이 깨집니다. 이미 있는 객체의 Content-Encoding이 다르면 덮어쓰지 않고 실패합니다. 원격 GET 검증은 `Accept-Encoding: gzip`으로 저장된 바이트를 해시합니다.

HLOD 노드 JSON은 지역 tileset을 `/api/map-data/world-buildings/...` 절대 경로로 가리킵니다. R2에서는 호스트 루트 기준이라 깨지므로, 이 링크만 상대 경로(`../../../national-regions-gzip-v2/<id>/tileset.json`)로 바꾼 사본을 올립니다. 상대 경로는 로컬 서버와 R2에서 같은 파일로 풀립니다. 봉인된 로컬 파일은 바꾸지 않습니다. 업로드 직전 로컬 바이트가 봉인 SHA256과 같은지 확인하고, 바뀐 사본의 크기·SHA256은 영수증 행에 `sourceSHA256`·`sourceBytes`와 함께 남습니다. 공개 전송 목록 hash도 바뀐 사본 기준입니다.

원격 manifest의 `terrain.url`·`nationalBuildings.url`은 `/api/map-data/...` 그대로 두고 `assetBases`(`world-buildings`, `terrain`)만 추가합니다. 편집기는 `mapAssetUrl`로 이 base를 적용합니다. v2에는 Scene PMTiles가 없어 `tiles/buildings/latest.json`은 건드리지 않습니다.

v2 업로드는 로컬 브라우저 PASS 영수증이 있어야 시작하지만, 원격 `releases/current.json`은 쓰지 않습니다(결과 `uploaded-unpromoted`). 로컬 PASS는 `/api/map-data` 바이트를 잰 것이고, R2의 링크 바꾼 사본·gzip 헤더·CORS는 아직 렌더된 적이 없기 때문입니다.

```powershell
C:/Python313/python.exe -X utf8 infra/data/r2_release.py --data-root C:/Data/25_ACE --release-id <sealed-v2-id> --env-file .env.r2.local --upload --runtime-validation <browser-pass.json>
```

그다음 `NEXT_PUBLIC_MAP_RELEASE_URL=<public-base>/releases/<remoteReleaseId>/manifest.json`인 격리 편집기로 브라우저 PASS를 다시 재고, 영수증에 `remoteReleaseId`와 `baseUrl`(public base)을 넣습니다. 공개 포인터는 그 영수증으로만 승격합니다. `--expected-current`는 지금 원격 current의 releaseId(처음이면 `none`)이고, 다르면 쓰지 않고 `CURRENT_POINTER_CHANGED`로 실패합니다. 쓰기는 조건부(`If-Match` 현재 ETag, 없으면 `If-None-Match: *`)라 읽기와 쓰기 사이에 다른 쓰기가 끼어도 덮지 않습니다. 영수증은 봉인된 원본 릴리스(`filesReceiptSHA256`, `isolatedCandidate`)에 묶여야 합니다. 중단된 옛 업로드가 새 릴리스를 되돌리는 일을 막고, v1 업로드는 원격 current가 v2면 `CURRENT_IS_V2`로 거부합니다.

```powershell
C:/Python313/python.exe -X utf8 infra/data/r2_release.py --data-root C:/Data/25_ACE --release-id <sealed-v2-id> --env-file .env.r2.local --promote <remoteReleaseId> --expected-current <current-or-none> --runtime-validation <r2-browser-pass.json>
```

계획은 봉인된 `files.jsonl`을 매번 스트리밍으로 읽고 메모리에 쌓지 않습니다. dry-run은 1회, 업로드는 2회 읽습니다(전송 목록 hash, 업로드). 매번 HLOD 노드 JSON 약 1만 개를 다시 읽고 바꿉니다. 실측 약 50초입니다. dry-run 출력의 `rewrittenLinkFiles`는 바꾼 사본 수입니다(현재 HLOD 기준 7,091).

오프라인 회귀 테스트:

```powershell
cd infra/data
C:/Python313/python.exe -X utf8 -m unittest test_r2_release -v
```
