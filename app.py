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
    if 'selected_campaign' not in st.session_state:
        st.session_state.selected_campaign = None
    if 'email_accounts' not in st.session_state:
        st.session_state.email_accounts = []
    if 'csv_emails' not in st.session_state:
        st.session_state.csv_emails = []
    if 'email_mappings' not in st.session_state:
        st.session_state.email_mappings = {}
    if 'analysis' not in st.session_state:
        st.session_state.analysis = {}
    if 'processing_started' not in st.session_state:
        st.session_state.processing_started = False
    if 'error_count' not in st.session_state:
        st.session_state.error_count = 0

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
            st.session_state.step = 1
            st.session_state.processing_started = False

        # Navigation
        st.markdown("---")
        st.subheader("🧭 Navigation")

        steps = [
            (1, "📋 Select Campaign", st.session_state.step >= 1),
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

def validate_api_key(api_key: str) -> bool:
    """Validate API key format"""
    return bool(api_key and api_key.strip() and len(api_key.strip()) > 10)

def step_1_campaign_selection():
    """Step 1: Campaign selection"""
    st.header("📋 Step 1: Select Campaign")

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

    # Campaign selection
    try:
        selected_campaign = CampaignSelector.render(st.session_state.campaigns)

        if selected_campaign and st.button("Next Step →", key="step1_next", type="primary"):
            st.session_state.selected_campaign = selected_campaign
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

        # Display selected campaign info
        campaign = st.session_state.selected_campaign
        st.info(f"Selected Campaign: **{campaign.get('name')}** (ID: {campaign.get('id')})")

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
                    # Extract emails from CSV
                    st.session_state.csv_emails = processor.extract_emails_from_uploaded_file(uploaded_file)

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
                        st.session_state.email_mappings = {}
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

        # Get existing accounts in campaign
        with st.spinner("Checking existing accounts in campaign..."):
            try:
                # Use cached fetch for production optimization
                existing_campaign_accounts = cached_fetch_campaign_email_accounts(
                    st.session_state.api_key,
                    st.session_state.selected_campaign['id']
                )

                # Create mapping of existing accounts using normalized email fields
                existing_mapping = processor.build_campaign_email_lookup(existing_campaign_accounts)

                # Analyze changes
                st.session_state.analysis = processor.analyze_changes(
                    existing_mapping,
                    st.session_state.email_mappings
                )

            except Exception as e:
                st.error(f"Error checking campaign accounts: {str(e)}")
                logger.error(f"Campaign accounts check error: {e}")
                return False

        # Display summary
        SummaryDisplay.render(st.session_state.analysis, st.session_state.selected_campaign)

        # Confirmation
        if st.session_state.analysis['total_to_add'] > 0:
            st.markdown("---")
            st.warning("⚠️ **Please review the changes above carefully before proceeding.**")

            col1, col2 = st.columns(2)

            with col1:
                if st.button("🚀 Execute Changes", key="execute_changes", type="primary"):
                    st.session_state.step = 5
                    st.session_state.processing_started = False  # Reset processing flag
                    st.rerun()

            with col2:
                if st.button("📤 Upload Different CSV", key="different_csv_preview"):
                    st.session_state.step = 3
                    st.session_state.csv_emails = []
                    st.session_state.email_mappings = {}
                    st.session_state.analysis = {}
                    st.rerun()
        else:
            st.info("No new accounts to add. All provided emails are already in the campaign.")

            if st.button("🔄 Start Over", key="restart_no_changes"):
                st.session_state.step = 1
                st.rerun()

    except Exception as e:
        st.error(f"Error in step 4: {str(e)}")
        logger.error(f"Step 4 error: {e}")
        return False

    return True

async def step_5_process():
    """Step 5: Execute the changes"""
    st.header("🚀 Step 5: Processing")

    try:
        client = SmartleadClient(st.session_state.api_key)
        processor = EmailDataProcessor()

        campaign_id = st.session_state.selected_campaign['id']
        accounts_to_add = list(st.session_state.analysis['to_add'].values())

        if not accounts_to_add:
            st.info("No accounts to add.")
            return True

        # Initialize processing if not started
        if not st.session_state.processing_started:
            st.session_state.processing_started = True
            st.session_state.processing_complete = False
            st.session_state.processing_results = {}

        # Create batches
        batches = processor.create_batch_requests(accounts_to_add, batch_size=50)
        total_batches = len(batches)

        st.info(f"Adding {len(accounts_to_add)} accounts to campaign in {total_batches} batches...")

        # Progress tracking
        progress_data = {
            'completed': st.session_state.get('processing_completed_batches', 0),
            'total': total_batches,
            'current_batch': st.session_state.get('processing_current_batch', 0),
            'total_batches': total_batches,
            'accounts_added': st.session_state.get('processing_accounts_added', 0),
            'errors': st.session_state.get('processing_errors', [])
        }

        # Process batches if not complete
        if not st.session_state.get('processing_complete', False):
            progress_bar = ProgressDisplay.render(progress_data)

            for i, batch in enumerate(batches):
                # Skip already processed batches
                if i < st.session_state.get('processing_completed_batches', 0):
                    continue

                try:
                    # Update progress
                    progress_data['current_batch'] = i + 1
                    progress_data['completed'] = i

                    with st.spinner(f"Processing batch {i + 1}/{total_batches}..."):
                        # Add accounts to campaign
                        result = client.add_email_accounts_to_campaign(campaign_id, batch)

                        # Update session state with progress
                        st.session_state.processing_completed_batches = i + 1
                        st.session_state.processing_current_batch = i + 1

                        if result.get('ok', False) or result.get('success', False):
                            added_count = len(batch)
                            st.session_state.processing_accounts_added = progress_data['accounts_added'] + added_count
                            progress_data['accounts_added'] = st.session_state.processing_accounts_added
                            logger.info(f"Batch {i + 1} successful: {added_count} accounts added")
                        else:
                            error_msg = f"Batch {i + 1} failed: {result}"
                            progress_data['errors'].append(error_msg)
                            st.session_state.processing_errors = progress_data['errors']
                            logger.error(error_msg)

                    # Update progress bar
                    progress_bar.progress((i + 1) / total_batches)
                    ProgressDisplay.render(progress_data)

                    # Small delay to avoid overwhelming the API
                    await asyncio.sleep(0.5)

                    # Force a rerun to show progress
                    st.rerun()

                except Exception as e:
                    error_msg = f"Batch {i + 1} error: {str(e)}"
                    progress_data['errors'].append(error_msg)
                    st.session_state.processing_errors = progress_data['errors']
                    logger.error(error_msg)

            # Mark processing as complete
            st.session_state.processing_complete = True
            st.session_state.processing_completed_batches = total_batches

        # Final update
        progress_data['completed'] = total_batches
        progress_data['accounts_added'] = st.session_state.get('processing_accounts_added', 0)
        progress_data['errors'] = st.session_state.get('processing_errors', [])
        ProgressDisplay.render(progress_data)

        # Results
        st.markdown("---")
        st.header("🎉 Results")

        col1, col2 = st.columns(2)

        with col1:
            if progress_data['accounts_added'] > 0:
                st.success(f"✅ Successfully added **{progress_data['accounts_added']}** accounts to the campaign")
            else:
                st.warning("⚠️ No accounts were added")

        with col2:
            if progress_data['errors']:
                st.error(f"❌ **{len(progress_data['errors'])}** errors occurred")
            else:
                st.success("✅ No errors occurred")

        # Completion options
        st.markdown("---")
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("🔄 Process Another CSV", key="process_another"):
                st.session_state.step = 3
                st.session_state.csv_emails = []
                st.session_state.email_mappings = []
                st.session_state.analysis = {}
                # Reset processing state
                st.session_state.processing_started = False
                st.session_state.processing_complete = False
                st.session_state.processing_completed_batches = 0
                st.session_state.processing_accounts_added = 0
                st.session_state.processing_errors = []
                st.rerun()

        with col2:
            if st.button("📊 Select Different Campaign", key="different_campaign"):
                st.session_state.step = 1
                st.session_state.selected_campaign = None
                st.session_state.csv_emails = []
                st.session_state.email_mappings = []
                st.session_state.analysis = {}
                # Reset processing state
                st.session_state.processing_started = False
                st.session_state.processing_complete = False
                st.session_state.processing_completed_batches = 0
                st.session_state.processing_accounts_added = 0
                st.session_state.processing_errors = []
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