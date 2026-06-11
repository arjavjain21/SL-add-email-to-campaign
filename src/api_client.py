import concurrent.futures
import json
import logging
import math
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}


class SmartleadAPIError(Exception):
    """Structured exception for Smartlead API failures."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _sanitize_secret(value: str) -> str:
    """Redact API keys and common tokens from logged URLs/messages."""
    if not value:
        return value
    return re.sub(r"(?i)(api_key|token|authorization)=([^&\s]+)", r"\1=[REDACTED]", str(value))


def _parse_json_or_text(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw_text": response.text[:1000]}


class SmartleadClient:
    """
    Smartlead API Client for campaign and email account management.

    This client provides methods to:
    - Fetch campaigns with optional filtering
    - Fetch all email accounts with fast concurrent pagination support
    - Fetch email accounts already in a campaign
    - Add email accounts to campaigns with batch processing
    - Look up individual account records through the optional inbox lookup service
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
        self.base_url = os.getenv("SMARTLEAD_BASE_URL", "https://server.smartlead.ai/api/v1").rstrip("/")
        self.lookup_base_url = os.getenv(
            "SLINBOXES_LOOKUP_BASE_URL",
            "https://slinboxes.eagleinfoservice.com/api",
        ).rstrip("/")
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
        params = dict(params or {})
        params['api_key'] = self.api_key

        max_retries = _env_int('MAX_RETRIES', 3)
        timeout = _env_int('REQUEST_TIMEOUT', 30)
        retry_delay = _env_float('RETRY_DELAY_SECONDS', 1.0)

        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"Making {method} request to {_sanitize_secret(url)}")

                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_data,
                    timeout=timeout,
                )

                if 200 <= response.status_code < 300:
                    try:
                        return response.json()
                    except json.JSONDecodeError:
                        logger.warning(f"Response is not valid JSON: {response.text[:1000]}")
                        return response.text

                payload = _parse_json_or_text(response)
                message = (
                    payload.get('error')
                    or payload.get('message')
                    if isinstance(payload, dict)
                    else str(payload)
                )
                error_message = (
                    f"Smartlead API error {response.status_code} for {method} "
                    f"{_sanitize_secret(response.url)}: {message or payload}"
                )

                if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except ValueError:
                            delay = retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    else:
                        delay = retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning(
                        f"{error_message}; retrying in {delay:.2f}s "
                        f"(attempt {attempt}/{max_retries})"
                    )
                    time.sleep(delay)
                    continue

                logger.error(error_message)
                raise SmartleadAPIError(error_message, response.status_code, payload)

            except requests.exceptions.RequestException as e:
                sanitized_error = _sanitize_secret(str(e))
                if attempt == max_retries:
                    logger.error(f"Request failed after {max_retries} attempts: {sanitized_error}")
                    raise

                delay = retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                logger.warning(
                    f"Request failed (attempt {attempt}/{max_retries}), "
                    f"retrying in {delay:.2f}s: {sanitized_error}"
                )
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

        if isinstance(campaigns, dict):
            campaigns = campaigns.get('data', campaigns)

        if not isinstance(campaigns, list):
            logger.warning(f"Expected list of campaigns, got {type(campaigns)}")
            campaigns = [campaigns] if campaigns else []

        logger.info(f"Fetched {len(campaigns)} campaigns")
        return campaigns

    def _normalize_accounts_payload(self, accounts: Any) -> List[Dict]:
        if isinstance(accounts, dict):
            accounts = accounts.get('data', accounts)
        if not isinstance(accounts, list):
            accounts = [accounts] if accounts else []
        valid_accounts = []
        for account in accounts:
            if isinstance(account, dict) and account.get('id'):
                valid_accounts.append(account)
            else:
                logger.warning(f"Skipping invalid account data: {account}")
        return valid_accounts

    def _fetch_email_accounts_page(self, offset: int, limit: int, fetch_campaigns: bool) -> Dict[str, Any]:
        """Fetch one email-account page with local-session retries for thread safety."""
        params = {
            'api_key': self.api_key,
            'limit': limit,
            'offset': offset,
        }
        if fetch_campaigns:
            params['fetch_campaigns'] = 'true'

        url = f"{self.base_url}/email-accounts/"
        max_retries = _env_int('MAX_RETRIES', 5)
        timeout = _env_int('REQUEST_TIMEOUT', 60)
        retry_delay = _env_float('RETRY_DELAY_SECONDS', 1.0)
        started = time.perf_counter()

        with requests.Session() as session:
            session.headers.update({
                'Accept': 'application/json',
                'User-Agent': 'Smartlead-Python-Client/fast-fetch/1.0',
            })

            for attempt in range(1, max_retries + 1):
                try:
                    response = session.get(url, params=params, timeout=timeout)
                    elapsed = time.perf_counter() - started
                    payload = _parse_json_or_text(response)

                    if response.status_code == 200:
                        accounts = self._normalize_accounts_payload(payload)
                        return {
                            'offset': offset,
                            'records': accounts,
                            'record_count': len(accounts),
                            'attempts': attempt,
                            'elapsed_seconds': round(elapsed, 4),
                            'error': None,
                        }

                    if response.status_code in NON_RETRYABLE_STATUS_CODES:
                        raise SmartleadAPIError(
                            f"Smartlead returned {response.status_code} at offset {offset}: {payload}",
                            response.status_code,
                            payload,
                        )

                    if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
                        retry_after = response.headers.get('Retry-After')
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except ValueError:
                                delay = retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                        else:
                            delay = retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                        logger.warning(
                            f"Email-account page offset {offset} returned {response.status_code}; "
                            f"retrying in {delay:.2f}s (attempt {attempt}/{max_retries})"
                        )
                        time.sleep(delay)
                        continue

                    raise SmartleadAPIError(
                        f"Unexpected Smartlead status {response.status_code} at offset {offset}: {payload}",
                        response.status_code,
                        payload,
                    )

                except SmartleadAPIError as e:
                    if e.status_code in NON_RETRYABLE_STATUS_CODES or attempt == max_retries:
                        raise
                    delay = retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    time.sleep(delay)
                except requests.exceptions.RequestException as e:
                    if attempt == max_retries:
                        return {
                            'offset': offset,
                            'records': [],
                            'record_count': 0,
                            'attempts': attempt,
                            'elapsed_seconds': None,
                            'error': _sanitize_secret(str(e)),
                        }
                    delay = retry_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning(
                        f"Email-account page offset {offset} request failed; retrying in {delay:.2f}s: "
                        f"{_sanitize_secret(str(e))}"
                    )
                    time.sleep(delay)

        return {
            'offset': offset,
            'records': [],
            'record_count': 0,
            'attempts': max_retries,
            'elapsed_seconds': None,
            'error': 'Unknown failure after retries',
        }

    def _fetch_email_account_offsets(self, offsets: List[int], limit: int, fetch_campaigns: bool, concurrency: int) -> List[Dict[str, Any]]:
        page_results: List[Dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_offset = {
                executor.submit(self._fetch_email_accounts_page, offset, limit, fetch_campaigns): offset
                for offset in offsets
            }
            for completed, future in enumerate(concurrent.futures.as_completed(future_to_offset), start=1):
                offset = future_to_offset[future]
                try:
                    page_results.append(future.result())
                except Exception as e:
                    page_results.append({
                        'offset': offset,
                        'records': [],
                        'record_count': 0,
                        'attempts': _env_int('MAX_RETRIES', 5),
                        'elapsed_seconds': None,
                        'error': _sanitize_secret(str(e)),
                    })
                if completed % 10 == 0 or completed == len(future_to_offset):
                    logger.info(f"Completed {completed}/{len(future_to_offset)} email-account page requests")
        return page_results

    def fetch_all_email_accounts(self, limit: int = 500, fetch_campaigns: Optional[bool] = None) -> List[Dict]:
        """
        Fetch all email accounts with fast concurrent pagination support.

        Args:
            limit: Number of accounts to fetch per page (default: 500)
            fetch_campaigns: Whether Smartlead should include campaign associations in account records.

        Returns:
            List of all unique email account dictionaries.
        """
        fetch_campaigns = _env_bool('EMAIL_FETCH_CAMPAIGNS', False) if fetch_campaigns is None else fetch_campaigns
        concurrency = max(1, _env_int('EMAIL_FETCH_CONCURRENCY', 30))
        expected_accounts = max(1, _env_int('EMAIL_FETCH_EXPECTED_ACCOUNTS', 30000))
        overfetch_multiplier = max(1.0, _env_float('EMAIL_FETCH_OVERFETCH_MULTIPLIER', 1.25))

        if not _env_bool('EMAIL_FETCH_FAST_MODE', True) or concurrency == 1:
            return self._fetch_all_email_accounts_sequential(limit=limit, fetch_campaigns=fetch_campaigns)

        logger.info(
            "Starting fast concurrent email-account fetch "
            f"limit={limit}, concurrency={concurrency}, expected_accounts={expected_accounts}, "
            f"overfetch_multiplier={overfetch_multiplier}, fetch_campaigns={fetch_campaigns}"
        )
        started = time.perf_counter()
        expected_pages = max(math.ceil((expected_accounts * overfetch_multiplier) / limit), 10)
        next_page_start = 0
        all_page_results: List[Dict[str, Any]] = []

        while True:
            offsets = [page * limit for page in range(next_page_start, next_page_start + expected_pages)]
            logger.info(
                f"Fetching email-account offsets {offsets[0]} to {offsets[-1]} "
                f"using {len(offsets)} concurrent page requests"
            )
            batch_results = self._fetch_email_account_offsets(offsets, limit, fetch_campaigns, concurrency)
            all_page_results.extend(batch_results)

            failed_pages = [page for page in batch_results if page.get('error')]
            if failed_pages:
                failed_offsets = ', '.join(str(page['offset']) for page in sorted(failed_pages, key=lambda page: page['offset']))
                raise RuntimeError(f"Failed to fetch Smartlead email-account pages at offsets: {failed_offsets}")

            sorted_batch = sorted(batch_results, key=lambda page: page['offset'])
            terminal_pages = [page for page in sorted_batch if page['record_count'] < limit]
            if terminal_pages:
                first_terminal_offset = min(page['offset'] for page in terminal_pages)
                logger.info(f"Detected end of email accounts around offset {first_terminal_offset}")
                break

            logger.info("All fetched email-account pages were full. Extending search window.")
            next_page_start += expected_pages
            expected_pages = max(25, concurrency)

        all_page_results = sorted(all_page_results, key=lambda page: page['offset'])
        terminal_offsets = [page['offset'] for page in all_page_results if page['record_count'] < limit]
        if terminal_offsets:
            first_terminal_offset = min(terminal_offsets)
            usable_page_results = [page for page in all_page_results if page['offset'] <= first_terminal_offset]
        else:
            usable_page_results = all_page_results

        unique_by_id: Dict[Any, Dict] = {}
        duplicate_count = 0
        raw_count = 0
        for page in usable_page_results:
            raw_count += len(page['records'])
            for account in page['records']:
                account_id = account.get('id')
                if account_id in unique_by_id:
                    duplicate_count += 1
                unique_by_id[account_id] = account

        unique_accounts = list(unique_by_id.values())
        elapsed = time.perf_counter() - started
        logger.info(
            "Finished fast email-account fetch: "
            f"{len(unique_accounts)} unique accounts, {raw_count} raw records, "
            f"{duplicate_count} duplicate IDs removed, {len(usable_page_results)} usable pages, "
            f"{len(all_page_results)} requested pages in {elapsed:.1f}s"
        )
        return unique_accounts

    def _fetch_all_email_accounts_sequential(self, limit: int = 500, fetch_campaigns: bool = False) -> List[Dict]:
        """Fetch all email accounts sequentially as a conservative fallback."""
        all_accounts = []
        offset = 0
        page_count = 0

        logger.info(f"Starting sequential email-account fetch with limit={limit}, fetch_campaigns={fetch_campaigns}")

        while True:
            page_count += 1
            params = {
                'limit': limit,
                'offset': offset,
            }
            if fetch_campaigns:
                params['fetch_campaigns'] = 'true'

            logger.debug(f"Fetching page {page_count} with offset {offset}")
            accounts = self._make_request('GET', '/email-accounts/', params=params)
            valid_accounts = self._normalize_accounts_payload(accounts)
            all_accounts.extend(valid_accounts)
            logger.info(f"Fetched page {page_count}: {len(valid_accounts)} accounts (total: {len(all_accounts)})")

            if len(valid_accounts) < limit:
                logger.info(f"Reached end of accounts (got {len(valid_accounts)} < limit {limit})")
                break

            offset += limit

        unique_by_id = {}
        for account in all_accounts:
            unique_by_id[account.get('id')] = account
        logger.info(f"Finished sequential email-account fetch: {len(unique_by_id)} total unique accounts from {page_count} pages")
        return list(unique_by_id.values())

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

        if isinstance(accounts, dict):
            accounts = accounts.get('data', accounts)

        if not isinstance(accounts, list):
            logger.warning(f"Expected list of email accounts, got {type(accounts)}")
            accounts = [accounts] if accounts else []

        logger.info(f"Fetched {len(accounts)} email accounts for campaign {campaign_id}")
        return accounts

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

            added_count = result.get('added_count', len(email_account_ids)) if isinstance(result, dict) else len(email_account_ids)
            logger.info(f"Successfully added {added_count} accounts to campaign {campaign_id}")

            return result

        except Exception as e:
            logger.error(f"Failed to add accounts to campaign {campaign_id}: {_sanitize_secret(str(e))}")
            raise

    def lookup_email_account_by_email(self, email: str) -> Optional[Dict]:
        """Look up one account by email through the inbox lookup service."""
        if not email:
            return None

        url = f"{self.lookup_base_url}/accounts/lookup"
        timeout = _env_int('ACCOUNT_LOOKUP_TIMEOUT', 20)
        try:
            response = requests.get(
                url,
                params={'email': email},
                headers={'Accept': 'application/json', 'User-Agent': 'Smartlead-Python-Client/account-lookup/1.0'},
                timeout=timeout,
            )
            payload = _parse_json_or_text(response)
            if response.status_code != 200:
                logger.warning(f"Lookup endpoint returned {response.status_code} for {email}: {payload}")
                return None
            if isinstance(payload, dict) and payload.get('success') and isinstance(payload.get('data'), dict):
                return payload['data']
            logger.warning(f"Lookup endpoint did not find account for {email}: {payload}")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Lookup endpoint failed for {email}: {_sanitize_secret(str(e))}")
            return None

    def lookup_email_accounts_by_email(self, emails: List[str]) -> Dict[str, Dict]:
        """Look up multiple account records concurrently by email."""
        if not emails or not _env_bool('ACCOUNT_LOOKUP_FALLBACK_ENABLED', True):
            return {}

        concurrency = max(1, _env_int('ACCOUNT_LOOKUP_CONCURRENCY', 20))
        found_accounts: Dict[str, Dict] = {}
        logger.info(f"Looking up {len(emails)} missing email accounts through fallback endpoint")

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_email = {
                executor.submit(self.lookup_email_account_by_email, email): email
                for email in emails
            }
            for future in concurrent.futures.as_completed(future_to_email):
                email = future_to_email[future]
                try:
                    account = future.result()
                except Exception as e:
                    logger.warning(f"Fallback lookup failed for {email}: {e}")
                    continue
                if account and account.get('id'):
                    found_accounts[email] = account

        logger.info(f"Fallback lookup found {len(found_accounts)} out of {len(emails)} missing accounts")
        return found_accounts

    def get_campaign_details(self, campaign_id: int) -> Dict:
        """
        Get detailed information about a specific campaign.

        Args:
            campaign_id: ID of the campaign

        Returns:
            Campaign details dictionary
        """
        logger.info(f"Fetching details for campaign {campaign_id}")
        return self._make_request('GET', f'/campaigns/{campaign_id}')

    def validate_api_key(self) -> bool:
        """
        Validate the API key by making a simple request.

        Returns:
            True if API key is valid, False otherwise
        """
        try:
            self.fetch_campaigns()
            return True
        except Exception as e:
            logger.error(f"API key validation failed: {_sanitize_secret(str(e))}")
            return False
