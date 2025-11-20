import requests
import time
import logging
from typing import List, Dict, Any, Optional
import json

logger = logging.getLogger(__name__)


class SmartleadClient:
    """
    Smartlead API Client for campaign and email account management.

    This client provides methods to:
    - Fetch campaigns with optional filtering
    - Fetch all email accounts with pagination support (handles 16k+ accounts)
    - Fetch email accounts already in a campaign
    - Add email accounts to campaigns with batch processing
    """

    def __init__(self, api_key: str):
        """
        Initialize the Smartlead API client.

        Args:
            api_key: Smartlead API key for authentication

        Raises:
            ValueError: If api_key is None or empty
        """
        if not api_key or not api_key.strip():
            raise ValueError("API key is required")

        self.api_key = api_key.strip()
        self.base_url = "https://server.smartlead.ai/api/v1"
        self.session = requests.Session()

        # Configure session headers
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Smartlead-Python-Client/1.0'
        })

    def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Any:
        """
        Make HTTP request with error handling and retries.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: URL parameters
            json_data: JSON data for POST requests

        Returns:
            Response data as JSON

        Raises:
            requests.exceptions.RequestException: If request fails after retries
        """
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        params['api_key'] = self.api_key

        max_retries = 3
        retry_delay = 1  # Base delay in seconds

        for attempt in range(max_retries):
            try:
                # Log request details (without sensitive data)
                logger.debug(f"Making {method} request to {url}")

                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_data,
                    timeout=30  # 30 second timeout
                )

                response.raise_for_status()

                # Try to parse JSON response
                try:
                    return response.json()
                except json.JSONDecodeError:
                    logger.warning(f"Response is not valid JSON: {response.text}")
                    return response.text

            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
                    raise

                # Exponential backoff with jitter
                delay = retry_delay * (2 ** attempt) + (attempt * 0.1)
                logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}), retrying in {delay:.2f}s: {e}")
                time.sleep(delay)

    def fetch_campaigns(self, client_id: Optional[int] = None, include_tags: bool = False) -> List[Dict]:
        """
        Fetch all campaigns from Smartlead.

        Args:
            client_id: Optional client ID to filter campaigns
            include_tags: Whether to include campaign tags

        Returns:
            List of campaign dictionaries
        """
        params = {}
        if client_id:
            params['client_id'] = client_id
        if include_tags:
            params['include_tags'] = 'true'

        logger.info(f"Fetching campaigns with params: {params}")
        campaigns = self._make_request('GET', '/campaigns', params=params)

        # Ensure we return a list
        if isinstance(campaigns, dict):
            # API might return a dict with data field
            campaigns = campaigns.get('data', campaigns)

        if not isinstance(campaigns, list):
            logger.warning(f"Expected list of campaigns, got {type(campaigns)}")
            campaigns = [campaigns] if campaigns else []

        logger.info(f"Fetched {len(campaigns)} campaigns")
        return campaigns

    def fetch_all_email_accounts(self, limit: int = 100) -> List[Dict]:
        """
        Fetch all email accounts with pagination support.

        This method efficiently handles large numbers of email accounts (16k+)
        by fetching them in batches and combining the results.

        Args:
            limit: Number of accounts to fetch per page (default: 100)

        Returns:
            List of all email account dictionaries
        """
        all_accounts = []
        offset = 0
        page_count = 0
        max_empty_pages = 3  # Stop after 3 consecutive empty pages
        empty_page_count = 0

        logger.info(f"Starting to fetch all email accounts with limit={limit}")

        while True:
            page_count += 1

            try:
                params = {
                    'limit': limit,
                    'offset': offset
                }

                logger.debug(f"Fetching page {page_count} with offset {offset}")
                accounts = self._make_request('GET', '/email-accounts', params=params)

                # Handle different response formats
                if isinstance(accounts, dict):
                    # API might return a dict with data field
                    accounts = accounts.get('data', accounts)

                # Convert to list if necessary
                if not isinstance(accounts, list):
                    accounts = [accounts] if accounts else []

                if not accounts:
                    empty_page_count += 1
                    logger.debug(f"Page {page_count} is empty ({empty_page_count}/{max_empty_pages})")

                    if empty_page_count >= max_empty_pages:
                        logger.info(f"Stopping pagination after {max_empty_pages} empty pages")
                        break

                    # Continue with next page in case there are more accounts
                    offset += limit
                    continue

                # Reset empty page counter when we find accounts
                empty_page_count = 0

                # Validate account data
                valid_accounts = []
                for account in accounts:
                    if isinstance(account, dict) and account.get('id'):
                        valid_accounts.append(account)
                    else:
                        logger.warning(f"Skipping invalid account data: {account}")

                all_accounts.extend(valid_accounts)
                logger.info(f"Fetched page {page_count}: {len(valid_accounts)} accounts (total: {len(all_accounts)})")

                # If we got fewer accounts than the limit, we're likely at the end
                if len(accounts) < limit:
                    logger.info(f"Reached end of accounts (got {len(accounts)} < limit {limit})")
                    break

                offset += limit

                # Add small delay to avoid overwhelming the API
                if page_count % 10 == 0:  # Every 10 pages
                    time.sleep(0.1)

            except Exception as e:
                logger.error(f"Error fetching page {page_count}: {e}")
                # Continue to next page instead of failing completely
                offset += limit
                continue

        logger.info(f"Finished fetching email accounts: {len(all_accounts)} total accounts from {page_count} pages")
        return all_accounts

    def fetch_campaign_email_accounts(self, campaign_id: int) -> List[Dict]:
        """
        Fetch email accounts already in a specific campaign.

        Args:
            campaign_id: ID of the campaign

        Returns:
            List of email account dictionaries in the campaign
        """
        logger.info(f"Fetching email accounts for campaign {campaign_id}")

        accounts = self._make_request('GET', f'/campaigns/{campaign_id}/email-accounts')

        # Handle different response formats
        if isinstance(accounts, dict):
            accounts = accounts.get('data', accounts)

        if not isinstance(accounts, list):
            accounts = [accounts] if accounts else []

        # Validate account data
        valid_accounts = []
        for account in accounts:
            if isinstance(account, dict) and account.get('id'):
                valid_accounts.append(account)
            else:
                logger.warning(f"Skipping invalid campaign account data: {account}")

        logger.info(f"Fetched {len(valid_accounts)} email accounts for campaign {campaign_id}")
        return valid_accounts

    def add_email_accounts_to_campaign(self, campaign_id: int, email_account_ids: List[int]) -> Dict:
        """
        Add email accounts to a campaign.

        Args:
            campaign_id: ID of the target campaign
            email_account_ids: List of email account IDs to add

        Returns:
            Response dictionary from the API
        """
        if not email_account_ids:
            logger.warning(f"No email account IDs provided for campaign {campaign_id}")
            return {"ok": True, "added_count": 0, "message": "No accounts to add"}

        logger.info(f"Adding {len(email_account_ids)} email accounts to campaign {campaign_id}")

        json_data = {'email_account_ids': email_account_ids}

        try:
            result = self._make_request(
                'POST',
                f'/campaigns/{campaign_id}/email-accounts',
                json_data=json_data
            )

            # Log success
            added_count = result.get('added_count', len(email_account_ids))
            logger.info(f"Successfully added {added_count} accounts to campaign {campaign_id}")

            return result

        except Exception as e:
            logger.error(f"Failed to add accounts to campaign {campaign_id}: {e}")
            raise

    def get_campaign_details(self, campaign_id: int) -> Dict:
        """
        Get detailed information about a specific campaign.

        Args:
            campaign_id: ID of the campaign

        Returns:
            Campaign details dictionary
        """
        logger.info(f"Fetching details for campaign {campaign_id}")

        details = self._make_request('GET', f'/campaigns/{campaign_id}')

        if not isinstance(details, dict):
            logger.warning(f"Expected dict for campaign details, got {type(details)}")
            details = {}

        return details

    def validate_api_key(self) -> bool:
        """
        Validate the API key by making a simple request.

        Returns:
            True if API key is valid, False otherwise
        """
        try:
            # Try to fetch campaigns as a validation check
            self.fetch_campaigns()
            return True
        except Exception as e:
            logger.error(f"API key validation failed: {e}")
            return False

    def get_rate_limit_info(self) -> Dict:
        """
        Get rate limit information if available.

        Returns:
            Dictionary with rate limit info, empty if not available
        """
        # This would need to be implemented based on actual Smartlead API documentation
        # For now, return a placeholder
        return {
            "requests_per_minute": "Unknown",
            "requests_per_hour": "Unknown"
        }