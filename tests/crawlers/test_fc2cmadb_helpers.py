import pytest

from amane.crawlers.sites.fc2cmadb import FC2CMADBCrawler


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"props":{"status":404}}', 404),
        ('{"component":"Article","props":{"article":{"video_id":4975102}}}', None),
        ("[]", None),
        ("invalid", None),
    ],
)
def test_fc2cmadb_inertia_payload_status(raw: str, expected: int | None) -> None:
    assert FC2CMADBCrawler._inertia_status(FC2CMADBCrawler._decode_json(raw)) == expected


def test_fc2cmadb_article_fields_support_inertia_shapes() -> None:
    payload = {
        "props": {
            "article": {
                "data": {
                    "title": "current title",
                    "writer": {"name": "current writer"},
                    "actresses": [{"name": "actor one"}, {"name": "actor two"}],
                    "tags": [{"name": "tag one"}],
                }
            }
        }
    }
    article = FC2CMADBCrawler._article(payload)
    assert FC2CMADBCrawler._first_string(article, "title") == "current title"
    assert FC2CMADBCrawler._first_name(article, "writer") == "current writer"
    assert FC2CMADBCrawler._names(article, "actresses") == ["actor one", "actor two"]
    assert FC2CMADBCrawler._names(article, "tags") == ["tag one"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("02:05:33", 125), ("40:16", 40), ("125 分", 125), (None, None), ("unknown", None)],
)
def test_fc2cmadb_runtime_minutes(value: object, expected: int | None) -> None:
    assert FC2CMADBCrawler._runtime(value) == expected
