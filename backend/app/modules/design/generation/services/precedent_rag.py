"""
B3 — Precedent RAG (Phase 2)

원리 (Principle):
    Retrieval-Augmented Generation. 건축 사례 (text 설명 + 메타데이터)를 *벡터 임베딩*
    으로 인덱싱 → 사용자가 *유사 사례* 검색.

    예: "남북으로 긴 1300% 용적률 부지" → "역삼동 강남파이낸스센터", "테헤란로 N 빌딩" 등 사례 반환.

데이터 소스:
    - Phase 2 demo: hand-curated 사례 corpus (~10-30 건)
    - 향후: 도시건축통합지도 + 잡지 + 학술 발표 자료

검색 흐름:
    1. 사용자 query (or 부지 features) → text 변환
    2. OpenAI text-embedding-3-large (3072-dim) 로 embed
    3. cosine similarity 로 top-K corpus item 반환

저장:
    - corpus: `04_DATASETS/data/precedent_corpus.json` (gitignore)
    - embeddings: `04_DATASETS/data/precedent_embeddings.npy` (gitignore)

본 모듈은 *외부 API 의존* (OpenAI). offline fallback: 키워드 매칭.

사용법:
    from design.services.precedent_rag import PrecedentRAG
    rag = PrecedentRAG()
    rag.load_or_build()
    results = rag.search("강남 일반상업지역 1300% FAR", top_k=3)
"""

from backend.app.modules.design.generation import paths as _design_paths

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


# Demo corpus — 한국 매스 사례 placeholder.
# 실제 운영 시 도시건축통합지도 / 매거진 / 학술 자료 로 확장.
DEMO_CORPUS: list[dict] = [
    {
        "id": "case_001",
        "name": "강남 테헤란로 일반상업 — 매스 형태 'tower_podium'",
        "zone": "일반상업지역",
        "bcr_pct": 80, "far_pct": 1300, "height_limit_m": 50,
        "aspect_ratio": 1.2,
        "typology": "tower_podium",
        "description": "역삼동 일대 사례. 1~3F 저층 commercial podium + 상층 office tower. BCR 80%까지 채우고 상층은 step-back으로 일조/조망 확보.",
        "tags": ["상업", "오피스", "도심", "tower-podium", "고밀"],
    },
    {
        "id": "case_002",
        "name": "분당 신도시 2종 일반주거 — 매스 'courtyard'",
        "zone": "제2종일반주거지역",
        "bcr_pct": 60, "far_pct": 250, "height_limit_m": 25,
        "aspect_ratio": 1.0,
        "typology": "courtyard",
        "description": "분당 신도시 아파트. 중정형 매스로 대지 안의 공지 + 정북일조 동시 만족. 4-8층, 9-12세대/층.",
        "tags": ["주거", "아파트", "신도시", "courtyard", "정북일조"],
    },
    {
        "id": "case_003",
        "name": "춘천 1종 일반주거 — 매스 'lshape'",
        "zone": "제1종일반주거지역",
        "bcr_pct": 60, "far_pct": 200, "height_limit_m": 20,
        "aspect_ratio": 1.5,
        "typology": "lshape",
        "description": "춘천 단독/연립 주거. L자형으로 도로변 채광 + 후면 마당 확보. 4-6층 규모.",
        "tags": ["주거", "저층", "지방", "lshape"],
    },
    {
        "id": "case_004",
        "name": "도심 좁은 부지 — 매스 'cross'",
        "zone": "준주거지역",
        "bcr_pct": 70, "far_pct": 500, "height_limit_m": 35,
        "aspect_ratio": 0.8,
        "typology": "cross",
        "description": "도심 좁은 직사각 부지. 십자형 매스로 전후좌우 채광 동시. 코어 중앙.",
        "tags": ["도심", "준주거", "cross", "코어중앙"],
    },
    {
        "id": "case_005",
        "name": "광활한 부지 — 매스 'hshape'",
        "zone": "제3종일반주거지역",
        "bcr_pct": 50, "far_pct": 300, "height_limit_m": 30,
        "aspect_ratio": 2.0,
        "typology": "hshape",
        "description": "넓고 긴 부지에 H자형 2동 + 연결 브리지. 두 동 사이 정원, 입주자 커뮤니티 공간.",
        "tags": ["주거", "광활", "hshape", "커뮤니티"],
    },
    {
        "id": "case_006",
        "name": "방사형 광장 매스 — 'radial'",
        "zone": "일반상업지역",
        "bcr_pct": 80, "far_pct": 800, "height_limit_m": 40,
        "aspect_ratio": 1.0,
        "typology": "radial",
        "description": "원형/극좌표 매스. 광장형 부지에 6분할 sector 배열. 중앙 atrium.",
        "tags": ["상업", "광장", "radial", "atrium"],
    },
    {
        "id": "case_007",
        "name": "고층 주거 'tower_podium' (강남구)",
        "zone": "일반상업지역",
        "bcr_pct": 80, "far_pct": 1300, "height_limit_m": 50,
        "aspect_ratio": 1.0,
        "typology": "tower_podium",
        "description": "강남구 1300% 용적률 풀 활용. 5F podium (소매/주차) + 15F tower 주거. 정북일조 § 86①제2호 사선 만족.",
        "tags": ["고층", "주거", "tower-podium", "정북사선"],
    },
    {
        "id": "case_008",
        "name": "U자 공동주택 'ushape' (분당)",
        "zone": "제2종일반주거지역",
        "bcr_pct": 60, "far_pct": 250, "height_limit_m": 25,
        "aspect_ratio": 1.3,
        "typology": "ushape",
        "description": "U자 매스 — 가운데 마당 + 양쪽 동. 8층, 4세대/층. 일조 + 통풍 + 조망 모두 우수.",
        "tags": ["주거", "ushape", "마당", "통풍"],
    },
    {
        "id": "case_009",
        "name": "박스 적층 사례 'additive'",
        "zone": "일반상업지역",
        "bcr_pct": 80, "far_pct": 1300, "height_limit_m": 50,
        "aspect_ratio": 1.1,
        "typology": "additive",
        "description": "5개 박스 적층 — 각 박스마다 위치/회전/크기 자유. 비정형 입면. 갤러리/문화시설 흔함.",
        "tags": ["비정형", "additive", "갤러리", "문화"],
    },
    {
        "id": "case_010",
        "name": "정형 박스 'subtractive'",
        "zone": "준주거지역",
        "bcr_pct": 70, "far_pct": 400, "height_limit_m": 30,
        "aspect_ratio": 0.9,
        "typology": "subtractive",
        "description": "기본 박스에서 voids 빼기 — 정형이지만 외부 공간 (테라스, 발코니) 풍부.",
        "tags": ["정형", "subtractive", "테라스"],
    },
]


@dataclass
class PrecedentRAG:
    """Precedent corpus + embeddings 검색."""
    corpus: list[dict] = field(default_factory=list)
    embeddings: np.ndarray | None = None
    embedding_model: str = "text-embedding-3-large"
    _api_key: str | None = None  # Code review fix: build → search 일관 전달

    def _corpus_text(self, item: dict) -> str:
        """corpus item 을 임베딩용 text 로 변환."""
        return (f"{item['name']} | {item['zone']} BCR{item['bcr_pct']}% "
                f"FAR{item['far_pct']}% H{item['height_limit_m']}m typology={item['typology']} | "
                f"{item['description']} 태그: {', '.join(item['tags'])}")

    def build_offline(self, corpus: list[dict] | None = None) -> None:
        """API 없이 — fallback 모드. embedding 없음, 키워드 매칭 사용."""
        self.corpus = corpus if corpus is not None else DEMO_CORPUS
        self.embeddings = None  # offline mode
        logger.info(f"PrecedentRAG offline mode: {len(self.corpus)} items, no embeddings")

    def build_with_openai(self, corpus: list[dict] | None = None,
                          api_key: str | None = None) -> None:
        """OpenAI text-embedding-3-large 로 corpus 인덱싱."""
        try:
            import openai
        except ImportError:
            logger.warning("openai package not installed — fallback to offline mode")
            return self.build_offline(corpus)

        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set — fallback to offline mode")
            return self.build_offline(corpus)

        self.corpus = corpus if corpus is not None else DEMO_CORPUS
        self._api_key = api_key  # Code review fix: search 에서 재사용
        client = openai.OpenAI(api_key=api_key)
        texts = [self._corpus_text(item) for item in self.corpus]
        try:
            resp = client.embeddings.create(model=self.embedding_model, input=texts)
            E = np.asarray([d.embedding for d in resp.data], dtype=np.float32)
            # Code review fix: build 시점에 정규화 (search 매번 정규화 비용 제거)
            norms = np.linalg.norm(E, axis=1, keepdims=True)
            self.embeddings = E / np.where(norms > 0, norms, 1.0)
            logger.info(f"PrecedentRAG online mode: {len(self.corpus)} items, "
                        f"embeddings shape={self.embeddings.shape} (pre-normalized)")
        except Exception as e:
            logger.error(f"OpenAI embedding failed: {e} — fallback offline")
            self.build_offline(corpus)

    def save(self, dir_path: str | None = None) -> None:
        """corpus.json + embeddings.npy 저장."""
        if dir_path is None:
            dir_path = _design_paths.package_root('design') / "research" / "04_DATASETS" / "data"
        dir_path = Path(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        (dir_path / "precedent_corpus.json").write_text(
            json.dumps(self.corpus, indent=2, ensure_ascii=False), encoding="utf-8")
        if self.embeddings is not None:
            np.save(dir_path / "precedent_embeddings.npy", self.embeddings)
        logger.info(f"Saved PrecedentRAG → {dir_path}")

    def load(self, dir_path: str | None = None) -> bool:
        """파일에서 로드. 성공 시 True."""
        if dir_path is None:
            dir_path = _design_paths.package_root('design') / "research" / "04_DATASETS" / "data"
        dir_path = Path(dir_path)
        corpus_path = dir_path / "precedent_corpus.json"
        emb_path = dir_path / "precedent_embeddings.npy"

        if not corpus_path.exists():
            return False
        self.corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        if emb_path.exists():
            self.embeddings = np.load(emb_path)
        logger.info(f"Loaded PrecedentRAG: {len(self.corpus)} items, "
                    f"embeddings={'yes' if self.embeddings is not None else 'no (offline)'}")
        return True

    def load_or_build(self) -> None:
        """저장된 인덱스 로드 또는 신규 생성."""
        if self.load():
            return
        self.build_with_openai()
        self.save()

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """query → top-K precedent."""
        if not self.corpus:
            self.load_or_build()

        if self.embeddings is not None:
            # Online: cosine similarity (embeddings already normalized at build)
            try:
                import openai
                # Code review fix: build 때 사용한 api_key 우선, 없으면 env
                api_key = self._api_key or os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    raise RuntimeError("OPENAI_API_KEY missing for search")
                client = openai.OpenAI(api_key=api_key)
                resp = client.embeddings.create(model=self.embedding_model, input=[query])
                qv = np.asarray(resp.data[0].embedding, dtype=np.float32)
                qv_norm = np.linalg.norm(qv)
                if qv_norm == 0:
                    raise RuntimeError("zero-norm query embedding")
                qv = qv / qv_norm
                sims = self.embeddings @ qv  # already normalized
                top_idx = np.argsort(-sims)[:top_k]
                return [
                    {**self.corpus[int(i)], "similarity": float(sims[i])}
                    for i in top_idx
                ]
            except Exception as e:
                logger.warning(f"online search failed: {e}, fallback to keyword")

        # Offline fallback: keyword + zone + typology matching
        return self._keyword_search(query, top_k)

    def _keyword_search(self, query: str, top_k: int = 3) -> list[dict]:
        """간이 키워드 매칭 (offline fallback)."""
        q_lower = query.lower()
        scored = []
        for item in self.corpus:
            txt = self._corpus_text(item).lower()
            # Score = number of word matches
            words = q_lower.split()
            matches = sum(1 for w in words if w in txt)
            # Bonus: zone direct match
            if item["zone"] in query:
                matches += 5
            # Bonus: typology mention
            if item["typology"] in q_lower:
                matches += 3
            if matches > 0:
                scored.append((matches, item))
        scored.sort(key=lambda x: -x[0])
        return [{**item, "similarity": float(score) / 10.0}
                for score, item in scored[:top_k]]


__all__ = [
    "DEMO_CORPUS",
    "PrecedentRAG",
]
