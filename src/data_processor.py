import pandas as pd
import io
import re
from typing import List, Dict, Set, Tuple
import logging

logger = logging.getLogger(__name__)

class EmailDataProcessor:
    """Handle CSV processing and email account mapping"""

    def __init__(self):
        self.email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

    def _normalize_email(self, email: str) -> str:
        """Normalize an email address to a comparable format."""
        if not isinstance(email, str):
            return ""

        normalized = email.strip().lower()
        return normalized if self.email_pattern.match(normalized) else ""

    def build_campaign_email_lookup(self, campaign_accounts: List[Dict]) -> Dict[str, int]:
        """Create a lookup of normalized emails for accounts already in the campaign."""

        email_lookup: Dict[str, int] = {}

        for account in campaign_accounts:
            account_id = account.get('id')
            if not account_id:
                logger.warning(f"Skipping campaign account without ID: {account}")
                continue

            # Collect unique normalized emails for this account
            normalized_emails = set()
            for field in ['username', 'from_email', 'email']:
                normalized_email = self._normalize_email(account.get(field, ''))
                if normalized_email:
                    normalized_emails.add(normalized_email)

            for normalized_email in normalized_emails:
                email_lookup[normalized_email] = account_id

        return email_lookup

    def extract_emails_from_csv_string(self, csv_content: str, email_column: str = 'email') -> List[str]:
        """Extract email addresses from CSV content"""
        try:
            df = pd.read_csv(io.StringIO(csv_content))

            # Try common email column names
            email_columns = [email_column, 'Email', 'EMAIL', 'email_address', 'emailaddress']

            for col in email_columns:
                if col in df.columns:
                    emails = df[col].dropna().astype(str).tolist()
                    valid_emails = []
                    for email in emails:
                        email = email.strip().lower()
                        if self.email_pattern.match(email):
                            valid_emails.append(email)
                        else:
                            logger.warning(f"Invalid email format: {email}")

                    return list(set(valid_emails))  # Remove duplicates

            raise ValueError("No email column found in CSV. Expected columns: " + ", ".join(email_columns))

        except Exception as e:
            logger.error(f"Error processing CSV: {e}")
            raise ValueError(f"Failed to process CSV: {str(e)}")

    def extract_emails_from_uploaded_file(self, uploaded_file, email_column: str = 'email') -> List[str]:
        """Extract emails from Streamlit uploaded file"""
        try:
            # Read file content
            stringio = io.StringIO(uploaded_file.read().decode("utf-8"))
            return self.extract_emails_from_csv_string(stringio.getvalue(), email_column)
        except UnicodeDecodeError:
            raise ValueError("File encoding not supported. Please save as UTF-8.")

    def map_emails_to_account_ids(self, emails: List[str], email_accounts: List[Dict]) -> Dict[str, int]:
        """Map email addresses to account IDs using Smartlead account data"""
        email_to_id = {}

        # Create lookup dictionary from email accounts
        account_lookup = {}
        for account in email_accounts:
            # Check multiple possible email fields
            email_fields = [
                account.get('username', '').lower(),
                account.get('from_email', '').lower(),
                account.get('email', '').lower()
            ]

            for email in email_fields:
                if email and self.email_pattern.match(email):
                    account_lookup[email] = account['id']

        # Map requested emails to account IDs
        for email in emails:
            # Normalize email to lowercase for consistent mapping
            normalized_email = email.lower()
            if normalized_email in account_lookup:
                email_to_id[normalized_email] = account_lookup[normalized_email]
            else:
                logger.warning(f"Email account not found: {normalized_email}")

        logger.info(f"Mapped {len(email_to_id)} out of {len(emails)} requested emails")
        return email_to_id

    def analyze_changes(self, existing_accounts: Dict[str, int], new_mappings: Dict[str, int]) -> Dict:
        """Analyze what needs to be added vs what already exists"""
        to_add = {}
        already_exists = {}
        not_found = []

        for email, account_id in new_mappings.items():
            if email in existing_accounts:
                if existing_accounts[email] == account_id:
                    already_exists[email] = account_id
                else:
                    # Different account ID, treat as new
                    to_add[email] = account_id
            else:
                to_add[email] = account_id

        return {
            'to_add': to_add,
            'already_exists': already_exists,
            'not_found': not_found,
            'total_requested': len(new_mappings),
            'total_to_add': len(to_add),
            'total_already_exists': len(already_exists)
        }

    def create_batch_requests(self, account_ids: List[int], batch_size: int = 50) -> List[List[int]]:
        """Split account IDs into batches for API requests"""
        batches = []
        for i in range(0, len(account_ids), batch_size):
            batches.append(account_ids[i:i + batch_size])
        return batches