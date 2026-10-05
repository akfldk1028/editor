"""Editor-native tools a saved team may call.

They wrap services the editor already runs in-process; no stored source code is
executed. Results are returned as text trimmed for a model context.
"""

import json

from pydantic import BaseModel, Field
from autogen_core import Component
from autogen_core.tools import BaseTool


_services = None


def set_tool_services(services):
    """Inject the services the tools call; None restores the lazy default."""
    global _services
    _services = services


def tool_services():
    global _services
    if _services is None:
        # Built lazily so importing this module never constructs Vworld clients.
        from backend.app.modules.land.services import LandServices

        _services = LandServices.from_environment()
    return _services


def trim_text(value, limit):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…(truncated)"


class _EmptyConfig(BaseModel):
    pass


class LandAnalyzeArgs(BaseModel):
    pnu: str = Field(default="", description="19-digit parcel number (PNU)")
    address: str = Field(default="", description="Road or lot address when the PNU is unknown")
    zones: list[str] = Field(default_factory=list, description="Zoning names to force, if known")


class LandAnalyzeTool(BaseTool[LandAnalyzeArgs, str], Component[_EmptyConfig]):
    component_config_schema = _EmptyConfig
    component_provider_override = "backend.app.adapters.workspace_tools.LandAnalyzeTool"

    DROPPED = ("setback_lines", "law_articles")

    def __init__(self):
        super().__init__(
            LandAnalyzeArgs,
            str,
            "analyze_land",
            "토지의 용도지역·건폐율·용적률·높이·규제 데이터를 조회한다. PNU 또는 주소 중 하나를 준다.",
        )

    async def run(self, args, cancellation_token):
        try:
            result = await tool_services().analyze_land(args.pnu, args.address, list(args.zones))
        except Exception as error:
            # The text goes to the model and on to the client; exception text may embed credentials.
            return json.dumps({"error": f"analyze_land failed ({type(error).__name__})"})
        slim = {key: value for key, value in result.items() if key not in self.DROPPED}
        return trim_text(slim, 12000)

    def _to_config(self):
        return _EmptyConfig()

    @classmethod
    def _from_config(cls, config):
        return cls()


class LawSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="Korean statute search query")
    limit: int = Field(default=5, ge=1, le=10)


class LawSearchTool(BaseTool[LawSearchArgs, str], Component[_EmptyConfig]):
    component_config_schema = _EmptyConfig
    component_provider_override = "backend.app.adapters.workspace_tools.LawSearchTool"

    def __init__(self):
        super().__init__(
            LawSearchArgs,
            str,
            "search_laws",
            "건축법·국토계획법 등 법조항을 검색한다. 조문 본문과 출처를 돌려준다.",
        )

    async def run(self, args, cancellation_token):
        try:
            result = await tool_services().search_laws(args.query, args.limit)
        except Exception as error:
            return json.dumps({"error": f"search_laws failed ({type(error).__name__})"})
        articles = result.get("articles") if isinstance(result, dict) else None
        if isinstance(articles, list):
            result = {
                **result,
                "articles": [
                    {
                        key: (value[:600] if isinstance(value, str) else value)
                        for key, value in article.items()
                    }
                    for article in articles[: args.limit]
                    if isinstance(article, dict)
                ],
            }
        return trim_text(result, 12000)

    def _to_config(self):
        return _EmptyConfig()

    @classmethod
    def _from_config(cls, config):
        return cls()
