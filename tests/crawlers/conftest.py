"""crawler 测试的共享 fixtures"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from amane.crawlers.http import HttpClient


@pytest.fixture
def mock_web_client():
    """提供一个 mock WebClient"""
    client = AsyncMock()
    client.register_source = MagicMock()
    return client


@pytest.fixture
def http_client(mock_web_client):
    """提供一个使用 mock WebClient 的 HttpClient 用于测试"""
    return HttpClient(web=mock_web_client)
