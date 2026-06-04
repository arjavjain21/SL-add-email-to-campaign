from src.api_client import SmartleadClient


def test_fetch_all_email_accounts_uses_500_limit_and_email_accounts_endpoint(monkeypatch):
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
        {
            "method": "GET",
            "endpoint": "/email-accounts/",
            "params": {"limit": 500, "offset": 500},
            "json_data": None,
        },
        {
            "method": "GET",
            "endpoint": "/email-accounts/",
            "params": {"limit": 500, "offset": 1000},
            "json_data": None,
        },
    ]
