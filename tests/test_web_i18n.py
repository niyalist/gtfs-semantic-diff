"""Web 静的ページの i18n 監査 (I2、docs/design/i18n.md §6)。

- en 出力にフィード由来データ以外の日本語 (CJK) が残らないことを機械検査する。
  対象領域はマーカーで区切る: index.html は `// en-dict-begin`〜`// en-dict-end`、
  terms/developers は `<!-- en:begin -->`〜`<!-- en:end -->`。
- index.html の ja/en 辞書はキー集合の一致 (ずれゼロ) を検査する。
- GtfsLoadError の英語文 (error_en の供給源) も確認する。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent / "web"

# ひらがな・カタカナ・CJK 漢字・全角記号 (＊は凡例で使うため除外しない —
# en 辞書・en ブロックに全角文字はデータ以外に現れない想定)
CJK = re.compile(r"[ぁ-んァ-ヶ一-鿿々〜、。「」・]")


def _between(text: str, begin: str, end: str) -> str:
    i = text.index(begin) + len(begin)
    j = text.index(end)
    # begin マーカー行自体 (日本語コメントを含み得る) を除外
    i = text.index("\n", i) + 1
    return text[i:j]


def _assert_no_cjk(region: str, label: str) -> None:
    hits = sorted({m.group(0) for line in region.splitlines()
                   for m in CJK.finditer(line)})
    offending = [line.strip() for line in region.splitlines()
                 if CJK.search(line)]
    assert not hits, f"{label}: 英語領域に日本語が残っています: {offending[:5]}"


@pytest.mark.parametrize("page", ["terms.html", "developers.html"])
def test_static_pages_en_block_has_no_cjk(page):
    text = (WEB / page).read_text("utf-8")
    _assert_no_cjk(_between(text, "<!-- en:begin -->", "<!-- en:end -->"), page)


def test_index_en_dict_has_no_cjk():
    text = (WEB / "index.html").read_text("utf-8")
    _assert_no_cjk(_between(text, "// en-dict-begin", "// en-dict-end"),
                   "index.html en 辞書")


def _dict_keys(region: str) -> set[str]:
    return set(re.findall(r"^    (\w+):", region, re.MULTILINE))


def test_index_dict_keys_match():
    text = (WEB / "index.html").read_text("utf-8")
    ja = _dict_keys(_between(text, "ja: {", "// en-dict-begin"))
    en = _dict_keys(_between(text, "// en-dict-begin", "// en-dict-end"))
    assert ja, "ja 辞書のキーが抽出できません (整形が変わったらテストを追従)"
    assert ja == en, f"辞書キーのずれ: ja-en={sorted(ja - en)} en-ja={sorted(en - ja)}"


def test_static_pages_have_lang_toggle():
    for page in ["index.html", "terms.html", "developers.html"]:
        text = (WEB / page).read_text("utf-8")
        assert 'data-lang="en"' in text and 'data-lang="ja"' in text, page
        assert 'localStorage.getItem("lang")' in text, page


def test_gtfs_load_error_carries_english():
    from gtfs_semantic_diff.load import GtfsLoadError
    from gtfs_semantic_diff.load.loader import _parser_error_message

    ja, en = _parser_error_message(
        "translations.txt",
        Exception("Error tokenizing data. C error: Expected 7 fields in line 3, saw 8"),
    )
    assert "3行目" in ja and "line 3" in en
    assert not CJK.search(en)

    e = GtfsLoadError("stops.txt が空です", en="stops.txt is empty")
    assert e.en == "stops.txt is empty"
    assert GtfsLoadError("日本語のみ").en == "日本語のみ"  # en 省略時は ja で代用
