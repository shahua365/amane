from ..enums import Language, MetadataField, SiteName
from .actor import (
    ActorCrawler,
    ActorMetadata,
    GFriendsActorCrawler,
    JavDBActorCrawler,
    MinnanoActorCrawler,
    ThePornDBActorCrawler,
    WikipediaActorCrawler,
    actor_registry,
)
from .base import Crawler
from .http import HttpClient
from .models import FetchOptions, FilmActor, MediaMetadata, film_actors
from .registry import registry
from .sites import (
    AiravCrawler,
    AvsoxCrawler,
    DahliaCrawler,
    DmmCrawler,
    FalenoCrawler,
    FC2ClubCrawler,
    FC2CMADBCrawler,
    FC2Crawler,
    FC2DBCrawler,
    FD2PPVCrawler,
    FourhoiCrawler,
    FreejavbtCrawler,
    GetchuCrawler,
    GigaCrawler,
    IqqtvCrawler,
    Jav321Crawler,
    JavArchiveCrawler,
    JavBusCrawler,
    JavDBCrawler,
    JavLibraryCrawler,
    Kin8Crawler,
    MGStageCrawler,
    OfficialCrawler,
    PaipanconCrawler,
    PPVDataBankCrawler,
    PrestigeCrawler,
    R18DevCrawler,
    ThePornDBCrawler,
    XCityCrawler,
)

registry.register(JavDBCrawler)
registry.register(DmmCrawler)
registry.register(JavBusCrawler)
registry.register(MGStageCrawler)
registry.register(FC2Crawler)
registry.register(JavLibraryCrawler)
registry.register(FreejavbtCrawler)
registry.register(Jav321Crawler)
registry.register(AiravCrawler)
registry.register(AvsoxCrawler)
registry.register(XCityCrawler)
registry.register(DahliaCrawler)
registry.register(FalenoCrawler)
registry.register(GigaCrawler)
registry.register(Kin8Crawler)
registry.register(FC2ClubCrawler)
registry.register(FC2CMADBCrawler)
registry.register(FC2DBCrawler)
registry.register(FD2PPVCrawler)
registry.register(FourhoiCrawler)
registry.register(JavArchiveCrawler)
registry.register(GetchuCrawler)
registry.register(IqqtvCrawler)
registry.register(PrestigeCrawler)
registry.register(R18DevCrawler)
registry.register(ThePornDBCrawler)
registry.register(OfficialCrawler)
registry.register(PaipanconCrawler)
registry.register(PPVDataBankCrawler)

# 演员站在 amane.crawlers.actor 导入时注册.

__all__ = [
    "ActorCrawler",
    "ActorMetadata",
    "AiravCrawler",
    "AvsoxCrawler",
    "Crawler",
    "DahliaCrawler",
    "DmmCrawler",
    "FC2CMADBCrawler",
    "FC2ClubCrawler",
    "FC2Crawler",
    "FC2DBCrawler",
    "FD2PPVCrawler",
    "FalenoCrawler",
    "FetchOptions",
    "FilmActor",
    "FourhoiCrawler",
    "FreejavbtCrawler",
    "GFriendsActorCrawler",
    "GetchuCrawler",
    "GigaCrawler",
    "HttpClient",
    "IqqtvCrawler",
    "Jav321Crawler",
    "JavArchiveCrawler",
    "JavBusCrawler",
    "JavDBActorCrawler",
    "JavDBCrawler",
    "JavLibraryCrawler",
    "Kin8Crawler",
    "Language",
    "MGStageCrawler",
    "MediaMetadata",
    "MetadataField",
    "MinnanoActorCrawler",
    "OfficialCrawler",
    "PPVDataBankCrawler",
    "PaipanconCrawler",
    "PrestigeCrawler",
    "R18DevCrawler",
    "SiteName",
    "ThePornDBActorCrawler",
    "ThePornDBCrawler",
    "WikipediaActorCrawler",
    "XCityCrawler",
    "actor_registry",
    "film_actors",
    "registry",
]
