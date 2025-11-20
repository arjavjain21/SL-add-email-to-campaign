import pytest

from src.data_processor import EmailDataProcessor


def test_build_campaign_email_lookup_normalizes_multiple_fields():
    processor = EmailDataProcessor()

    campaign_accounts = [
        {"id": 1, "username": "User@Example.com", "from_email": "user@example.com"},
        {"id": 2, "from_email": "Sender@Example.com", "email": "sender+alias@example.com"},
        {"id": 3, "username": "invalid-email"},
    ]

    lookup = processor.build_campaign_email_lookup(campaign_accounts)

    assert lookup == {
        "user@example.com": 1,
        "sender@example.com": 2,
        "sender+alias@example.com": 2,
    }


def test_analyze_changes_counts_existing_vs_new():
    processor = EmailDataProcessor()

    campaign_accounts = [
        {"id": 11, "username": "Existing@domain.com"},
        {"id": 12, "from_email": "already@domain.com"},
    ]

    existing_lookup = processor.build_campaign_email_lookup(campaign_accounts)

    uploaded_mappings = {
        "existing@domain.com": 11,
        "already@domain.com": 12,
        "new@domain.com": 15,
    }

    analysis = processor.analyze_changes(existing_lookup, uploaded_mappings)

    assert analysis["already_exists"] == {
        "existing@domain.com": 11,
        "already@domain.com": 12,
    }
    assert analysis["to_add"] == {"new@domain.com": 15}
    assert analysis["total_requested"] == 3
    assert analysis["total_already_exists"] == 2
    assert analysis["total_to_add"] == 1
