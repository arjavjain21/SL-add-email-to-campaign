from src.api_client import SmartleadClient


def test_fetch_all_email_accounts_sequential_uses_500_limit_and_endpoint(monkeypatch):
    monkeypatch.setenv("EMAIL_FETCH_FAST_MODE", "false")
    client = SmartleadClient("test-api-key-123")
    calls = []

    def fake_make_request(method, endpoint, params=None, json_data=None):
        calls.append({"method": method, "endpoint": endpoint, "params": params, "json_data": json_data})
        return []

    monkeypatch.setattr(client, "_make_request", fake_make_request)

    accounts = client.fetch_all_email_accounts()

    assert accounts == []
    assert calls == [
        {
            "method": "GET",
            "endpoint": "/email-accounts/",
            "params": {"limit": 500, "offset": 0},
            "json_data": None,
        },
    ]


def test_fetch_all_email_accounts_fast_fetches_offset_window_and_deduplicates(monkeypatch):
    monkeypatch.setenv("EMAIL_FETCH_FAST_MODE", "true")
    monkeypatch.setenv("EMAIL_FETCH_CONCURRENCY", "4")
    monkeypatch.setenv("EMAIL_FETCH_EXPECTED_ACCOUNTS", "2")
    monkeypatch.setenv("EMAIL_FETCH_OVERFETCH_MULTIPLIER", "1")
    client = SmartleadClient("test-api-key-123")
    seen_offsets = []

    def fake_fetch_offsets(offsets, limit, fetch_campaigns, concurrency):
        seen_offsets.extend(offsets)
        return [
            {"offset": 0, "records": [{"id": 1}, {"id": 2}], "record_count": 2, "error": None},
            {"offset": 2, "records": [{"id": 2}, {"id": 3}], "record_count": 2, "error": None},
            {"offset": 4, "records": [{"id": 4}], "record_count": 1, "error": None},
        ] + [
            {"offset": offset, "records": [], "record_count": 0, "error": None}
            for offset in offsets
            if offset not in {0, 2, 4}
        ]

    monkeypatch.setattr(client, "_fetch_email_account_offsets", fake_fetch_offsets)

    accounts = client.fetch_all_email_accounts(limit=2)

    assert seen_offsets == list(range(0, 20, 2))
    assert accounts == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]


def test_lookup_email_accounts_by_email_returns_found_accounts(monkeypatch):
    client = SmartleadClient("test-api-key-123")

    def fake_lookup(email):
        if email == "found@example.com":
            return {"id": 10, "from_email": email}
        return None

    monkeypatch.setattr(client, "lookup_email_account_by_email", fake_lookup)

    accounts = client.lookup_email_accounts_by_email(["found@example.com", "missing@example.com"])

    assert accounts == {"found@example.com": {"id": 10, "from_email": "found@example.com"}}
