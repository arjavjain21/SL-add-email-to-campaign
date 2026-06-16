import streamlit as st
import os
import logging
from typing import Dict, List, Any, Optional
import asyncio
import time
import sys
from dotenv import load_dotenv

from src.api_client import SmartleadClient
from src.data_processor import EmailDataProcessor
from src.ui_components import (
    ApiKeyInput,
    CampaignSelector,
    MultiCampaignSelector,
    EmailUploader,
    ProgressDisplay,
    SummaryDisplay,
)

# Load environment variables
load_dotenv()

# Configure production settings
if os.getenv('STREAMLIT_SERVER_HEADLESS', 'false').lower() == 'true':
    # Production optimizations
    st.set_option('server.maxUploadSize', int(os.getenv('MAX_FILE_SIZE_MB', 200)))
    st.set_option('server.maxMessageSize', 1000)

# Configure logging with production settings
log_level = getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper())
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Memory optimization functions
@st.cache_data(ttl=300)  # Cache for 5 minutes
def cached_fetch_campaigns(api_key: str) -> List[Dict]:
    """Cached version of campaigns fetch"""
    client = SmartleadClient(api_key)
    return client.fetch_campaigns(include_tags=True)

@st.cache_data(ttl=600)  # Cache for 10 minutes
def cached_fetch_email_accounts(api_key: str) -> List[Dict]:
    """Cached version of email accounts fetch"""
    client = SmartleadClient(api_key)
    return client.fetch_all_email_accounts()

@st.cache_data(ttl=1800)  # Cache for 30 minutes
def cached_fetch_campaign_email_accounts(api_key: str, campaign_id: int) -> List[Dict]:
    """Cached version of campaign email accounts fetch"""
    client = SmartleadClient(api_key)
    return client.fetch_campaign_email_accounts(campaign_id)

# Page configuration
st.set_page_config(
    page_title="Smartlead Campaign Manager",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)


def enforce_app_password():
    """Require a password before rendering the app."""
    app_password = st.secrets.get("APP_PASSWORD") if hasattr(st, "secrets") else None

    if not app_password:
        st.error("Application password not configured. Please set `APP_PASSWORD` in Streamlit secrets.")
        st.stop()

    if st.session_state.get("app_authenticated"):
        return True

    st.title("🔒 Secure Access")
    st.write("Enter the application password to continue.")

    with st.form("app_password_form"):
        password_input = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Unlock")

    if submitted:
        if password_input == app_password:
            st.session_state.app_authenticated = True
            st.success("Access granted. Loading application...")
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")
            st.stop()

    # Stop rendering the rest of the app until authenticated
    st.stop()

def validate_environment():
    """Validate required environment variables"""
    required_vars = []
    optional_vars = {
        'BATCH_SIZE': 50,
        'MAX_FILE_SIZE_MB': 200,
        'LOG_LEVEL': 'INFO',
        'REQUEST_TIMEOUT': 30,
        'MAX_RETRIES': 3
    }

    # Check required variables
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.warning(f"Missing environment variables: {missing_vars}")

    # Set defaults for optional variables
    for var, default in optional_vars.items():
        if not os.getenv(var):
            os.environ[var] = str(default)
            logger.info(f"Set default value for {var}: {default}")

    return True

def initialize_session_state():
    """Initialize Streamlit session state"""
    if 'step' not in st.session_state:
        st.session_state.step = 1
    if 'api_key' not in st.session_state:
        st.session_state.api_key = os.getenv('SMARTLEAD_API_KEY', '')
    if 'campaigns' not in st.session_state:
        st.session_state.campaigns = []
    if 'selected_campaigns' not in st.session_state:
        st.session_state.selected_campaigns = []  # Changed to list for multi-campaign
    if 'email_accounts' not in st.session_state:
        st.session_state.email_accounts = []
    if 'csv_emails' not in st.session_state:
        st.session_state.csv_emails = []
    if 'csv_dataframe' not in st.session_state:
        st.session_state.csv_dataframe = None
    if 'email_mappings' not in st.session_state:
        st.session_state.email_mappings = {}
    if 'analysis' not in st.session_state:
        st.session_state.analysis = {}
    if 'processing_started' not in st.session_state:
        st.session_state.processing_started = False
    if 'processing_status' not in st.session_state:
        st.session_state.processing_status = {}
    if 'error_count' not in st.session_state:
        st.session_state.error_count = 0
    # Multi-campaign processing state
    if 'current_campaign_index' not in st.session_state:
        st.session_state.current_campaign_index = 0
    if 'campaign_results' not in st.session_state:
        st.session_state.campaign_results = {}
    if 'analysis_per_campaign' not in st.session_state:
        st.session_state.analysis_per_campaign = {}

def render_sidebar():
    """Render sidebar with navigation and settings"""
    with st.sidebar:
        st.title("📧 Smartlead Manager")
        st.markdown("---")

        # API Key input
        st.subheader("🔑 Configuration")
        api_key = ApiKeyInput.render(st.session_state.api_key)

        if api_key != st.session_state.api_key:
            st.session_state.api_key = api_key
            # Reset data when API key changes
            st.session_state.campaigns = []
            st.session_state.email_accounts = []
            st.session_state.selected_campaigns = []
            st.session_state.step = 1
            st.session_state.processing_started = False

        # Navigation
        st.markdown("---")
        st.subheader("🧭 Navigation")

        steps = [
            (1, "📋 Select Campaigns", st.session_state.step >= 1),
            (2, "📥 Fetch Email Accounts", st.session_state.step >= 2),
            (3, "📤 Upload CSV", st.session_state.step >= 3),
            (4, "📊 Preview", st.session_state.step >= 4),
            (5, "🚀 Process", st.session_state.step >= 5)
        ]

        for step_num, title, enabled in steps:
            if enabled:
                st.success(f"✅ {title}")
            else:
                st.info(f"⏳ {title}")

        # Reset button
        st.markdown("---")
        if st.button("🔄 Reset All", help="Clear all data and start over"):
            for key in st.session_state.keys():
                del st.session_state[key]
            initialize_session_state()
            st.rerun()


def build_results_dataframe():
    """Create a dataframe with status information for download."""
    if st.session_state.csv_dataframe is None:
        return None

    status_map = st.session_state.get('processing_status', {})
    result_df = st.session_state.csv_dataframe.copy()

    def lookup_status(normalized_email: str):
        if not isinstance(normalized_email, str) or not normalized_email:
            return ("invalid_email", "Invalid email format")

        info = status_map.get(normalized_email)
        if info:
            return (info.get('status', 'unknown'), info.get('message', ''))

        return ("not_found", "Email account not found in Smartlead")

    status_detail = result_df['normalized_email'].apply(lookup_status)
    result_df['status'] = status_detail.apply(lambda item: item[0])
    result_df['status_detail'] = status_detail.apply(lambda item: item[1])

    if 'normalized_email' in result_df.columns:
        result_df = result_df.drop(columns=['normalized_email'])

    return result_df

def validate_api_key(api_key: str) -> bool:
    """Validate API key format"""
    return bool(api_key and api_key.strip() and len(api_key.strip()) > 10)

def step_1_campaign_selection():
    """Step 1: Campaign selection"""
    st.header("📋 Step 1: Select Campaigns")

    if not st.session_state.api_key:
        st.error("Please enter your Smartlead API key in the sidebar.")
        return False

    # Validate API key format
    if not validate_api_key(st.session_state.api_key):
        st.error("Please enter a valid Smartlead API key (should be at least 10 characters long).")
        return False

    # Initialize client
    try:
        client = SmartleadClient(st.session_state.api_key)
    except ValueError as e:
        st.error(f"Invalid API key: {str(e)}")
        return False

    # Fetch campaigns (with caching)
    if not st.session_state.campaigns:
        with st.spinner("Fetching campaigns..."):
            try:
                # Use cached fetch for production optimization
                st.session_state.campaigns = cached_fetch_campaigns(st.session_state.api_key)

                if not st.session_state.campaigns:
                    st.warning("No campaigns found. Please check your API key and permissions.")
                    return False

                st.success(f"Found {len(st.session_state.campaigns)} campaigns")
                logger.info(f"Successfully fetched {len(st.session_state.campaigns)} campaigns")
            except Exception as e:
                st.error(f"Failed to fetch campaigns: {str(e)}")
                logger.error(f"Campaign fetch error: {e}")
                return False

    # Multi-campaign selection
    try:
        selected_campaigns = MultiCampaignSelector.render(st.session_state.campaigns)

        if selected_campaigns and st.button("Next Step →", key="step1_next", type="primary"):
            st.session_state.selected_campaigns = selected_campaigns
            st.session_state.step = 2
            st.rerun()
    except Exception as e:
        st.error(f"Error rendering campaign selector: {str(e)}")
        logger.error(f"Campaign selector error: {e}")

    return True

def step_2_fetch_email_accounts():
    """Step 2: Fetch email accounts"""
    st.header("📥 Step 2: Fetch Email Accounts")

    try:
        client = SmartleadClient(st.session_state.api_key)

        # Display selected campaigns info
        selected_campaigns = st.session_state.selected_campaigns
        campaign_names = [c.get('name', 'Unknown') for c in selected_campaigns]
        st.info(f"**{len(selected_campaigns)} Campaign(s) Selected:** {', '.join(campaign_names)}")

        # Fetch email accounts button
        if not st.session_state.email_accounts:
            if st.button("🔄 Fetch All Email Accounts", key="fetch_accounts", type="primary"):
                with st.spinner("Fetching email accounts (this may take a while for large accounts)..."):
                    try:
                        start_time = time.time()
                        # Use cached fetch for production optimization
                        st.session_state.email_accounts = cached_fetch_email_accounts(st.session_state.api_key)

                        elapsed_time = time.time() - start_time
                        st.success(f"Successfully fetched {len(st.session_state.email_accounts)} email accounts in {elapsed_time:.1f} seconds")
                        logger.info(f"Fetched {len(st.session_state.email_accounts)} email accounts in {elapsed_time:.1f}s")

                        # Show account statistics
                        account_types = {}
                        active_accounts = 0

                        for account in st.session_state.email_accounts:
                            account_type = account.get('type', 'Unknown')
                            account_types[account_type] = account_types.get(account_type, 0) + 1

                            # Count active accounts
                            if account.get('is_smtp_success') and account.get('is_imap_success'):
                                active_accounts += 1

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Total Accounts", len(st.session_state.email_accounts))
                        with col2:
                            st.metric("Account Types", len(account_types))
                        with col3:
                            st.metric("Active Accounts", active_accounts)

                        # Show account type breakdown
                        if account_types:
                            st.subheader("Account Type Breakdown")
                            for account_type, count in account_types.items():
                                st.write(f"• **{account_type}**: {count} accounts")

                    except Exception as e:
                        st.error(f"Failed to fetch email accounts: {str(e)}")
                        logger.error(f"Email accounts fetch error: {e}")
                        return False

        # Continue if accounts are fetched
        if st.session_state.email_accounts:
            st.success(f"✅ {len(st.session_state.email_accounts)} email accounts loaded")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Next Step →", key="step2_next", type="primary"):
                    st.session_state.step = 3
                    st.rerun()

            with col2:
                if st.button("🔄 Refresh Accounts", key="refresh_accounts"):
                    st.session_state.email_accounts = []
                    st.rerun()

    except Exception as e:
        st.error(f"Error in step 2: {str(e)}")
        logger.error(f"Step 2 error: {e}")
        return False

    return True

def step_3_upload_csv():
    """Step 3: CSV upload and processing"""
    st.header("📤 Step 3: Upload Email List")

    try:
        processor = EmailDataProcessor()

        # Show current state
        st.info(f"Email accounts available: **{len(st.session_state.email_accounts)}**")

        # File upload
        uploaded_file, error = EmailUploader.render()

        if uploaded_file:
            try:
                with st.spinner("Processing CSV file..."):
                    st.session_state.processing_status = {}
                    st.session_state.csv_dataframe, st.session_state.csv_emails = processor.load_csv_with_emails(uploaded_file)

                    st.success(f"Found {len(st.session_state.csv_emails)} valid email addresses in CSV")

                    # Show sample
                    sample_emails = st.session_state.csv_emails[:10]
                    st.write("**Sample emails found:**")
                    for email in sample_emails:
                        st.text(f"• {email}")

                    if len(st.session_state.csv_emails) > 10:
                        st.text(f"... and {len(st.session_state.csv_emails) - 10} more")

            except Exception as e:
                st.error(f"Error processing CSV: {str(e)}")
                logger.error(f"CSV processing error: {e}")
                return False

        # Map emails to account IDs
        if st.session_state.csv_emails:
            if st.button("🔍 Map Emails to Accounts", key="map_emails", type="primary"):
                with st.spinner("Mapping emails to account IDs..."):
                    try:
                        st.session_state.email_mappings = processor.map_emails_to_account_ids(
                            st.session_state.csv_emails,
                            st.session_state.email_accounts
                        )

                        missing_emails = [
                            email for email in st.session_state.csv_emails
                            if email not in st.session_state.email_mappings
                        ]

                        if missing_emails:
                            st.info(
                                f"Looking up {len(missing_emails)} email(s) not found in the bulk Smartlead fetch..."
                            )
                            client = SmartleadClient(st.session_state.api_key)
                            lookup_accounts = client.lookup_email_accounts_by_email(missing_emails)

                            if lookup_accounts:
                                existing_account_ids = {
                                    account.get('id')
                                    for account in st.session_state.email_accounts
                                    if isinstance(account, dict)
                                }
                                for email, account in lookup_accounts.items():
                                    account_id = account.get('id')
                                    if account_id:
                                        st.session_state.email_mappings[email] = account_id
                                        if account_id not in existing_account_ids:
                                            st.session_state.email_accounts.append(account)
                                            existing_account_ids.add(account_id)

                                missing_emails = [
                                    email for email in st.session_state.csv_emails
                                    if email not in st.session_state.email_mappings
                                ]
                                st.success(
                                    f"Fallback lookup found {len(lookup_accounts)} additional account(s)."
                                )

                        # Track unmapped emails for reporting after fallback lookup has run
                        if st.session_state.csv_dataframe is not None:
                            status_map = st.session_state.processing_status
                            for email in st.session_state.csv_dataframe.get('normalized_email', []):
                                if not email:
                                    continue
                                if email in st.session_state.email_mappings:
                                    status_map.pop(email, None)
                                else:
                                    status_map[email] = {
                                        'status': 'not_found',
                                        'message': 'Email account not found in Smartlead bulk fetch or fallback lookup'
                                    }
                            st.session_state.processing_status = status_map

                        if st.session_state.email_mappings:
                            st.success(f"Mapped {len(st.session_state.email_mappings)} out of {len(st.session_state.csv_emails)} emails to account IDs")

                            # Show unmapped emails
                            unmapped_count = len(st.session_state.csv_emails) - len(st.session_state.email_mappings)
                            if unmapped_count > 0:
                                st.warning(f"⚠️ {unmapped_count} email(s) not found in your account")
                        else:
                            st.warning("No email accounts were found for the provided emails")
                            return False

                    except Exception as e:
                        st.error(f"Error mapping emails: {str(e)}")
                        logger.error(f"Email mapping error: {e}")
                        return False

            # Continue if mapping is complete
            if st.session_state.email_mappings:
                col1, col2 = st.columns(2)

                with col1:
                    if st.button("Next Step →", key="step3_next", type="primary"):
                        st.session_state.step = 4
                        st.rerun()

                with col2:
                    if st.button("📤 Upload Different CSV", key="upload_different"):
                        st.session_state.csv_emails = []
                        st.session_state.csv_dataframe = None
                        st.session_state.email_mappings = {}
                        st.session_state.processing_status = {}
                        st.rerun()

    except Exception as e:
        st.error(f"Error in step 3: {str(e)}")
        logger.error(f"Step 3 error: {e}")
        return False

    return True

def step_4_preview():
    """Step 4: Preview and analysis"""
    st.header("📊 Step 4: Preview Changes")

    try:
        processor = EmailDataProcessor()
        client = SmartleadClient(st.session_state.api_key)

        selected_campaigns = st.session_state.selected_campaigns
        analyses = {}  # Store analysis per campaign

        # Get existing accounts for each campaign
        with st.spinner(f"Checking existing accounts in {len(selected_campaigns)} campaign(s)..."):
            try:
                for campaign in selected_campaigns:
                    campaign_id = campaign['id']

                    # Use cached fetch for production optimization
                    existing_campaign_accounts = cached_fetch_campaign_email_accounts(
                        st.session_state.api_key,
                        campaign_id
                    )

                    # Create mapping of existing accounts using normalized email fields
                    existing_mapping = processor.build_campaign_email_lookup(existing_campaign_accounts)

                    # Analyze changes for this campaign
                    analysis = processor.analyze_changes(
                        existing_mapping,
                        st.session_state.email_mappings
                    )

                    analyses[campaign_id] = {
                        'campaign': campaign,
                        'analysis': analysis
                    }

                    logger.info(f"Campaign {campaign_id}: {analysis['total_to_add']} to add, {analysis['total_already_exists']} already exists")

                # Store analyses in session state
                st.session_state.analysis_per_campaign = analyses

                # Update status map for reporting (use first campaign as reference for "pending" status)
                status_map = st.session_state.processing_status
                for campaign_id, data in analyses.items():
                    for email in data['analysis']['already_exists'].keys():
                        if email not in status_map:
                            status_map[email] = {
                                'status': 'already_in_some_campaign',
                                'message': f'Email account already in campaign {campaign_id}'
                            }

                # Mark emails to add as pending across all campaigns
                for email in st.session_state.email_mappings.keys():
                    if email not in status_map or status_map[email]['status'] == 'not_found':
                        status_map[email] = {
                            'status': 'pending',
                            'message': 'Pending addition to campaign(s)'
                        }

                st.session_state.processing_status = status_map

            except Exception as e:
                st.error(f"Error checking campaign accounts: {str(e)}")
                logger.error(f"Campaign accounts check error: {e}")
                return False

        # Display summary for all campaigns
        st.subheader("📋 Campaign Summary")

        total_to_add_all = 0
        total_already_exists_all = 0

        for campaign_id, data in analyses.items():
            campaign = data['campaign']
            analysis = data['analysis']

            with st.expander(f"{campaign.get('name', 'Unknown')} (ID: {campaign_id})", expanded=len(selected_campaigns) <= 3):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Emails to Add", analysis['total_to_add'])
                with col2:
                    st.metric("Already in Campaign", analysis['total_already_exists'])
                with col3:
                    status = campaign.get('status', 'Unknown')
                    st.metric("Campaign Status", status)

            total_to_add_all += analysis['total_to_add']
            total_already_exists_all += analysis['total_already_exists']

        # Overall summary
        st.markdown("---")
        st.subheader("📊 Overall Summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Campaigns", len(selected_campaigns))
        with col2:
            st.metric("Total Adds Across All Campaigns", total_to_add_all)
        with col3:
            st.metric("Emails from CSV", len(st.session_state.csv_emails))

        # Confirmation
        if total_to_add_all > 0:
            st.markdown("---")
            st.warning(f"⚠️ **You are about to add {total_to_add_all} account(s) to {len(selected_campaigns)} campaign(s). Please review carefully.**")

            col1, col2 = st.columns(2)

            with col1:
                if st.button("🚀 Execute Changes", key="execute_changes", type="primary"):
                    st.session_state.step = 5
                    st.session_state.processing_started = False  # Reset processing flag
                    st.session_state.current_campaign_index = 0  # Reset campaign index
                    st.session_state.campaign_results = {}  # Reset results
                    st.rerun()

            with col2:
                if st.button("📤 Upload Different CSV", key="different_csv_preview"):
                    st.session_state.step = 3
                    st.session_state.csv_emails = []
                    st.session_state.csv_dataframe = None
                    st.session_state.email_mappings = {}
                    st.session_state.analysis_per_campaign = {}
                    st.session_state.processing_status = {}
                    st.rerun()
        else:
            st.info("No new accounts to add. All provided emails are already in all selected campaigns.")

            if st.button("🔄 Start Over", key="restart_no_changes"):
                st.session_state.step = 1
                st.session_state.selected_campaigns = []
                st.rerun()

    except Exception as e:
        st.error(f"Error in step 4: {str(e)}")
        logger.error(f"Step 4 error: {e}")
        return False

    return True

async def step_5_process():
    """Step 5: Execute the changes sequentially for each campaign"""
    st.header("🚀 Step 5: Processing")

    try:
        client = SmartleadClient(st.session_state.api_key)
        processor = EmailDataProcessor()

        selected_campaigns = st.session_state.selected_campaigns
        analyses = st.session_state.analysis_per_campaign
        current_idx = st.session_state.get('current_campaign_index', 0)

        if not selected_campaigns:
            st.error("No campaigns selected.")
            return False

        # Get accounts to add from analysis (same accounts for all campaigns)
        # Use the first campaign's analysis as reference
        first_campaign_id = selected_campaigns[0]['id']
        accounts_to_add = list(analyses[first_campaign_id]['analysis']['to_add'].items())

        if not accounts_to_add:
            st.info("No accounts to add.")
            return True

        # Initialize processing if not started
        if not st.session_state.processing_started:
            st.session_state.processing_started = True
            st.session_state.processing_complete = False
            st.session_state.campaign_results = {}

        # Overall progress tracking
        total_campaigns = len(selected_campaigns)
        total_batches_per_campaign = (len(accounts_to_add) + 49) // 50  # 50 accounts per batch
        total_operations = total_campaigns * total_batches_per_campaign

        st.info(f"Adding {len(accounts_to_add)} accounts to {total_campaigns} campaign(s)...")

        # Initialize status_map once at the beginning
        status_map = st.session_state.processing_status

        # Process campaigns sequentially
        for campaign_idx in range(current_idx, total_campaigns):
            campaign = selected_campaigns[campaign_idx]
            campaign_id = campaign['id']
            campaign_name = campaign.get('name', 'Unknown')

            st.markdown(f"---")
            st.subheader(f"📋 Processing Campaign {campaign_idx + 1}/{total_campaigns}: {campaign_name}")

            # Initialize campaign result if not exists
            if campaign_id not in st.session_state.campaign_results:
                st.session_state.campaign_results[campaign_id] = {
                    'campaign': campaign,
                    'accounts_added': 0,
                    'errors': [],
                    'status': 'in_progress',
                    'retry_attempt': 0
                }

            campaign_result = st.session_state.campaign_results[campaign_id]

            # Skip if already completed
            if campaign_result.get('status') == 'completed':
                st.success(f"✅ Campaign {campaign_name} already completed")
                continue

            # Create batches
            batches = [accounts_to_add[i:i + 50] for i in range(0, len(accounts_to_add), 50)]

            # Campaign-specific progress
            campaign_progress = {
                'completed': campaign_result.get('completed_batches', 0),
                'total': len(batches),
                'current_batch': campaign_result.get('current_batch', 0),
                'total_batches': len(batches),
                'accounts_added': campaign_result.get('accounts_added', 0),
                'errors': campaign_result.get('errors', [])
            }

            retry_attempt = campaign_result.get('retry_attempt', 0)
            max_retries = 1  # Retry once as per user requirement

            # Process batches for this campaign
            for i, batch in enumerate(batches):
                # Skip already processed batches
                if i < campaign_result.get('completed_batches', 0):
                    continue

                try:
                    # Update progress
                    campaign_progress['current_batch'] = i + 1
                    campaign_progress['completed'] = i

                    with st.spinner(f"Processing batch {i + 1}/{len(batches)} for {campaign_name}..."):
                        # Add accounts to campaign
                        account_ids = [account_id for _, account_id in batch]
                        result = client.add_email_accounts_to_campaign(campaign_id, account_ids)

                        # Update campaign progress
                        campaign_result['completed_batches'] = i + 1
                        campaign_result['current_batch'] = i + 1

                        if result.get('ok', False) or result.get('success', False):
                            added_count = len(batch)
                            campaign_result['accounts_added'] = campaign_progress['accounts_added'] + added_count
                            campaign_progress['accounts_added'] = campaign_result['accounts_added']
                            for email, _ in batch:
                                status_map[email] = {
                                    'status': 'added',
                                    'message': f'Successfully added to {campaign_name}'
                                }
                            logger.info(f"Batch {i + 1} for {campaign_name}: {added_count} accounts added")
                        else:
                            error_msg = f"Batch {i + 1} failed for {campaign_name}: {result}"
                            campaign_progress['errors'].append(error_msg)
                            campaign_result['errors'] = campaign_progress['errors']
                            for email, _ in batch:
                                status_map[email] = {
                                    'status': 'failed',
                                    'message': f'{result.get("message") or result.get("error") or str(result)} (Campaign: {campaign_name})'
                                }
                            logger.error(error_msg)

                    # Small delay to avoid overwhelming the API
                    await asyncio.sleep(0.5)

                    # Update session state and rerun to show progress
                    st.session_state.campaign_results[campaign_id] = campaign_result
                    st.session_state.processing_status = status_map
                    st.session_state.current_campaign_index = campaign_idx
                    st.rerun()

                except Exception as e:
                    error_msg = f"Batch {i + 1} error for {campaign_name}: {str(e)}"
                    campaign_progress['errors'].append(error_msg)
                    campaign_result['errors'] = campaign_progress['errors']
                    for email, _ in batch:
                        status_map[email] = {
                            'status': 'failed',
                            'message': f'{str(e)} (Campaign: {campaign_name})'
                        }
                    logger.error(error_msg)

            # Campaign processing complete - check if we need to retry
            if campaign_progress['errors'] and retry_attempt < max_retries:
                st.warning(f"⚠️ Campaign {campaign_name} had errors. Retrying once...")
                campaign_result['retry_attempt'] = retry_attempt + 1
                campaign_result['completed_batches'] = 0  # Reset to retry from beginning
                st.session_state.campaign_results[campaign_id] = campaign_result
                st.session_state.current_campaign_index = campaign_idx  # Stay on this campaign
                st.rerun()
                return True

            # Mark campaign as complete
            campaign_result['status'] = 'completed'
            st.session_state.campaign_results[campaign_id] = campaign_result

            # Move to next campaign
            st.session_state.current_campaign_index = campaign_idx + 1
            st.session_state.processing_status = status_map

            # Rerun to show next campaign
            st.rerun()

        # All campaigns processed
        st.session_state.processing_complete = True
        st.session_state.processing_status = status_map

        # Display final results
        st.markdown("---")
        st.header("🎉 Final Results")

        total_added = sum(r.get('accounts_added', 0) for r in st.session_state.campaign_results.values())
        total_errors = sum(len(r.get('errors', [])) for r in st.session_state.campaign_results.values())

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Campaigns Processed", len(st.session_state.campaign_results))

        with col2:
            if total_added > 0:
                st.success(f"✅ **{total_added}** accounts added across all campaigns")
            else:
                st.warning("⚠️ No accounts were added")

        with col3:
            if total_errors > 0:
                st.error(f"❌ **{total_errors}** errors occurred")
            else:
                st.success("✅ No errors occurred")

        # Per-campaign results
        st.markdown("---")
        st.subheader("📋 Campaign-Specific Results")

        for campaign_id, result in st.session_state.campaign_results.items():
            campaign = result['campaign']
            campaign_name = campaign.get('name', 'Unknown')

            with st.expander(f"{campaign_name} (ID: {campaign_id})", expanded=True):
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.metric("Accounts Added", result.get('accounts_added', 0))

                with col2:
                    st.metric("Errors", len(result.get('errors', [])))

                with col3:
                    st.metric("Status", result.get('status', 'unknown').capitalize())

                if result.get('errors'):
                    st.error("Errors encountered:")
                    for error in result['errors'][:5]:  # Show first 5 errors
                        st.text(f"- {error}")
                    if len(result['errors']) > 5:
                        st.text(f"... and {len(result['errors']) - 5} more")

        # Download results
        result_df = build_results_dataframe()
        if result_df is not None:
            result_csv = result_df.to_csv(index=False)
            st.download_button(
                "⬇️ Download Results CSV",
                data=result_csv,
                file_name="multi_campaign_results.csv",
                mime="text/csv"
            )

        # Completion options
        st.markdown("---")
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("🔄 Process Another CSV", key="process_another"):
                st.session_state.step = 3
                st.session_state.csv_emails = []
                st.session_state.csv_dataframe = None
                st.session_state.email_mappings = []
                st.session_state.analysis_per_campaign = {}
                # Reset processing state
                st.session_state.processing_started = False
                st.session_state.processing_complete = False
                st.session_state.current_campaign_index = 0
                st.session_state.campaign_results = {}
                st.session_state.processing_status = {}
                st.rerun()

        with col2:
            if st.button("📊 Select Different Campaigns", key="different_campaigns"):
                st.session_state.step = 1
                st.session_state.selected_campaigns = []
                st.session_state.csv_emails = []
                st.session_state.csv_dataframe = None
                st.session_state.email_mappings = []
                st.session_state.analysis_per_campaign = {}
                # Reset processing state
                st.session_state.processing_started = False
                st.session_state.processing_complete = False
                st.session_state.current_campaign_index = 0
                st.session_state.campaign_results = {}
                st.session_state.processing_status = {}
                st.rerun()

        with col3:
            if st.button("🏠 Start Over", key="start_over_complete"):
                for key in list(st.session_state.keys()):
                    if key != 'api_key':  # Keep API key
                        del st.session_state[key]
                initialize_session_state()
                st.rerun()

    except Exception as e:
        st.error(f"Error in step 5: {str(e)}")
        logger.error(f"Step 5 error: {e}")
        return False

    return True

def main():
    """Main application flow"""
    enforce_app_password()

    # Validate environment and initialize session state
    validate_environment()
    initialize_session_state()

    # Render sidebar
    render_sidebar()

    # Main content area
    st.title("📧 Smartlead Campaign Manager")
    st.markdown("Add email accounts from CSV files to your Smartlead campaigns efficiently")

    # Show API key warning if not set
    if not st.session_state.api_key:
        st.error("🔑 Please enter your Smartlead API key in the sidebar to begin.")
        st.markdown("""
        **How to get your API key:**
        1. Log in to your Smartlead account
        2. Go to Settings → API Keys
        3. Generate a new API key
        4. Copy and paste it in the sidebar
        """)
        return

    # Step-based workflow
    try:
        if st.session_state.step == 1:
            step_1_campaign_selection()
        elif st.session_state.step == 2:
            step_2_fetch_email_accounts()
        elif st.session_state.step == 3:
            step_3_upload_csv()
        elif st.session_state.step == 4:
            step_4_preview()
        elif st.session_state.step == 5:
            asyncio.run(step_5_process())

    except Exception as e:
        st.error(f"An unexpected error occurred: {str(e)}")
        logger.exception("Application error")

        # Show retry button
        if st.button("🔄 Retry Step", key="retry_step"):
            st.rerun()

if __name__ == "__main__":
    main()