import database
import finance


def test_price_cache_and_fallback(monkeypatch, tmp_path):
    path = tmp_path / "family.db"
    database.initialize_database(path, seed=False)
    monkeypatch.setattr(finance, "_download_quote", lambda symbol: (200.0, "USD"))
    assert finance.fetch_market_price("AAPL", db_path=path).price == 200
    monkeypatch.setattr(finance, "_download_quote", lambda symbol: (_ for _ in ()).throw(RuntimeError("offline")))
    result = finance.fetch_market_price("AAPL", 180, path)
    assert result.price == 200
    assert result.source == "마지막 저장 가격"
    assert finance.fetch_market_price("MSFT", 410, path).source == "수동 입력 가격"
