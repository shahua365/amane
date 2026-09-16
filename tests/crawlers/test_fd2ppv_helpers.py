from amane.crawlers.sites.fd2ppv import FD2PPVCrawler


def test_fd2ppv_clean_number_variants() -> None:
    assert FD2PPVCrawler._clean_number("FC2-3193265") == "3193265"
    assert FD2PPVCrawler._clean_number("FC2-PPV-3193265") == "3193265"
    assert FD2PPVCrawler._clean_number("FC2PPV3193265") == "3193265"
    assert FD2PPVCrawler._clean_number("FC2-invalid") == ""


def test_fd2ppv_title_from_current_page_title_shape() -> None:
    assert (
        FD2PPVCrawler._clean_title("FC2 PPV 3193265 至高ぷれみあ究極作品！ | 作品 - FD2", "3193265")
        == "至高ぷれみあ究極作品！"
    )
    assert FD2PPVCrawler._clean_title("", "3193265") is None


def test_fd2ppv_release_and_runtime_locales() -> None:
    text = "原創性 舊作重製 發佈日期 2023-02-25 片長 00:40:16 發行商 FC2"
    assert FD2PPVCrawler._parse_release(text) == "2023-02-25"
    assert FD2PPVCrawler._parse_runtime(text) == 40
