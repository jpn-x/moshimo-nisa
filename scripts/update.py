"""
投資信託の基準価額データを取得し docs/data/prices.json を更新する。

データソース: 各運用会社が自社サイトで配信している公開JSON/CSV
(emaxis.am.mufg.jp / am-one.co.jp / nam.co.jp / rakuten-toushin.co.jp)

いずれも無認証・robots.txt制限なし・利用規約上「自動的手段による取得」を
明示的に禁止していないことを個別に確認済み。

以下は自動取得を避け、本サイトのデータ源からは意図的に除外している:
- Yahoo!ファイナンス日本版（投信チャートは内部JWTトークンで保護）
- 投信総合検索ライブラリー・株探・みんかぶ（規約でスクレイピングを明示的に禁止）
- 大和アセットマネジメント（規約に電子的/機械的複製の禁止規定あり）
- 野村アセットマネジメント（同上の禁止規定あり。NEXT FUNDS系ETFのため）
- Yahoo Financeグローバル版のETF終値API（規約でロボット/スクレイパーによる
  自動収集を明示的に禁止しているため、ETF自体を本サイトの対象外としている）
"""
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "docs" / "data" / "prices.json"

UA = "Mozilla/5.0 (compatible; moshimo-nisa/1.0)"
JST = timezone(timedelta(hours=9))

# 投資信託マスタ: シンボル, 表示名, カテゴリ, 分類タグ, 通貨, データ源, 運用会社側ファンドコード
TRUST_TICKERS = [
    {"symbol": "TRUST-253144", "name": "eMAXIS Slim 国内株式（日経平均）", "category": "domestic", "tag": "日経225", "currency": "JPY", "source": "emaxis", "code": "253144"},
    {"symbol": "TRUST-252634", "name": "eMAXIS Slim 国内株式（TOPIX）", "category": "domestic", "tag": "TOPIX", "currency": "JPY", "source": "emaxis", "code": "252634"},
    {"symbol": "TRUST-313122", "name": "たわらノーロード 日経225", "category": "domestic", "tag": "日経225", "currency": "JPY", "source": "amone", "code": "313122"},
    {"symbol": "TRUST-121526", "name": "ニッセイ TOPIXインデックスファンド", "category": "domestic", "tag": "TOPIX", "currency": "JPY", "source": "nam", "code": "121526"},
    {"symbol": "TRUST-253266", "name": "eMAXIS Slim 米国株式（S&P500）", "category": "global", "tag": "米国S&P500", "currency": "JPY", "source": "emaxis", "code": "253266"},
    {"symbol": "TRUST-253425", "name": "eMAXIS Slim 全世界株式（オール・カントリー）", "category": "global", "tag": "全世界株", "currency": "JPY", "source": "emaxis", "code": "253425"},
    {"symbol": "TRUST-100087", "name": "楽天・プラス・S&P500インデックス・ファンド", "category": "global", "tag": "米国S&P500", "currency": "JPY", "source": "rakuten", "code": "100087"},
    {"symbol": "TRUST-100086", "name": "楽天・プラス・オールカントリー株式インデックス・ファンド", "category": "global", "tag": "全世界株", "currency": "JPY", "source": "rakuten", "code": "100086"},
    {"symbol": "TRUST-122308", "name": "ニッセイ NASDAQ100インデックスファンド", "category": "global", "tag": "NASDAQ100", "currency": "JPY", "source": "nam", "code": "122308"},
]


def fetch_json(url: str, retries: int = 3) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}") from last_err


def fetch_emaxis_series(code: str) -> dict:
    url = f"https://emaxis.am.mufg.jp/fund_file/chart/chart_data_{code}.js"
    d = fetch_json(url)
    series = {}
    for row in d["ROWS"]:
        price = row.get("BASE_PRICE")
        if price is None:
            continue
        raw = row["BASE_DATE"]  # YYYYMMDD
        date = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
        series[date] = round(float(price), 4)
    return series


def fetch_amone_series(code: str) -> dict:
    url = f"https://www.am-one.co.jp/chart_data/{code}/dat.json"
    d = fetch_json(url)
    series = {}
    for ts_ms, price in d["standard_price"]:
        if price is None:
            continue
        date = datetime.fromtimestamp(ts_ms / 1000, tz=JST).strftime("%Y-%m-%d")
        series[date] = round(float(price), 4)
    return series


def fetch_nam_series(code: str) -> dict:
    url = f"https://www.nam.co.jp/fundinfo/data/chart.php?fund_code={code}"
    d = fetch_json(url)
    series = {}
    for row in d[0]["graph-value1"]:
        price = row.get("data-nav")
        if price is None:
            continue
        series[row["data-date"]] = round(float(price), 4)
    return series


def fetch_rakuten_series(code: str) -> dict:
    url = f"https://www.rakuten-toushin.co.jp/assets/csv/chart_{code}.csv"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("cp932", errors="ignore")
    series = {}
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2 or not parts[0].strip():
            continue
        try:
            y, m, dd = parts[0].strip().split("/")
            date = f"{y}-{m.zfill(2)}-{dd.zfill(2)}"
            price = float(parts[1])
        except ValueError:
            continue
        series[date] = round(price, 4)
    return series


TRUST_FETCHERS = {
    "emaxis": fetch_emaxis_series,
    "amone": fetch_amone_series,
    "nam": fetch_nam_series,
    "rakuten": fetch_rakuten_series,
}


def main():
    existing = {}
    if DATA_PATH.exists():
        existing = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    out = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tickers": TRUST_TICKERS,
        "prices": {},
        "usdjpy": {},
    }

    for t in TRUST_TICKERS:
        symbol = t["symbol"]
        try:
            series = TRUST_FETCHERS[t["source"]](t["code"])
            print(f"OK  {symbol}: {len(series)} points")
            out["prices"][symbol] = series
        except Exception as e:
            print(f"NG  {symbol}: {e}")
            if symbol in existing.get("prices", {}):
                out["prices"][symbol] = existing["prices"][symbol]

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {DATA_PATH}")


if __name__ == "__main__":
    main()
