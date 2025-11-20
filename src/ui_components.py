import streamlit as st
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class CampaignSelector:
    """Component for selecting Smartlead campaigns"""

    @staticmethod
    def render(campaigns: List[Dict], key_prefix: str = "campaign") -> Optional[Dict]:
        """Render campaign selection interface"""
        if not campaigns:
            st.warning("No campaigns found. Please check your API key.")
            return None

        st.subheader("📋 Select Campaign")

        # Campaign filtering
        col1, col2 = st.columns([2, 1])

        with col1:
            search_term = st.text_input(
                "Search campaigns...",
                key=f"{key_prefix}_search",
                help="Search by campaign name"
            )

        with col2:
            status_filter = st.selectbox(
                "Filter by status",
                options=["All", "ACTIVE", "PAUSED", "DRAFTED", "COMPLETED", "STOPPED"],
                key=f"{key_prefix}_status"
            )

        # Filter campaigns
        filtered_campaigns = campaigns
        if search_term:
            filtered_campaigns = [c for c in campaigns if search_term.lower() in c.get('name', '').lower()]

        if status_filter != "All":
            filtered_campaigns = [c for c in filtered_campaigns if c.get('status') == status_filter]

        if not filtered_campaigns:
            st.info("No campaigns match your filters.")
            return None

        # Create display options
        campaign_options = {}
        for campaign in filtered_campaigns:
            status_emoji = CampaignSelector._get_status_emoji(campaign.get('status', ''))
            display_name = f"{status_emoji} {campaign.get('name', 'Unnamed')} (ID: {campaign.get('id')})"
            campaign_options[display_name] = campaign

        # Campaign selection
        selected_display = st.selectbox(
            "Choose a campaign:",
            options=list(campaign_options.keys()),
            key=f"{key_prefix}_select"
        )

        selected_campaign = campaign_options[selected_display]

        # Display campaign details
        with st.expander("Campaign Details", expanded=True):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("Status", selected_campaign.get('status', 'Unknown'))
                st.metric("Max Leads/Day", selected_campaign.get('max_leads_per_day', 'N/A'))

            with col2:
                created = selected_campaign.get('created_at', '')
                if created:
                    st.metric("Created", created.split('T')[0])

                client_id = selected_campaign.get('client_id')
                st.metric("Client ID", client_id if client_id else "None")

            with col3:
                st.metric("Campaign ID", selected_campaign.get('id'))
                min_time = selected_campaign.get('min_time_btwn_emails', 'N/A')
                st.metric("Min Time Between Emails", f"{min_time} min" if min_time != 'N/A' else min_time)

        return selected_campaign

    @staticmethod
    def _get_status_emoji(status: str) -> str:
        """Get emoji for campaign status"""
        status_emoji = {
            'ACTIVE': 'ACTIVE',
            'PAUSED': 'PAUSED',
            'DRAFTED': 'DRAFTED',
            'COMPLETED': 'COMPLETED',
            'STOPPED': 'STOPPED'
        }
        return status_emoji.get(status, 'UNKNOWN')

class EmailUploader:
    """Component for uploading and processing CSV files"""

    @staticmethod
    def render(key_prefix: str = "upload") -> Tuple[Optional[Any], Optional[str]]:
        """Render file upload interface"""
        st.subheader("📤 Upload Email List")

        # File upload instructions
        with st.expander("📖 Upload Instructions", expanded=False):
            st.markdown("""
            **CSV Requirements:**
            - File must be in CSV format
            - Include an 'email' column with valid email addresses
            - Additional columns are ignored

            **Example CSV:**
            ```csv
            email,name,company
            john@example.com,John Doe,Acme Corp
            jane@test.com,Jane Smith,Tech Inc
            ```
            """)

        # File upload
        uploaded_file = st.file_uploader(
            "Choose a CSV file",
            type=['csv'],
            help="Upload a CSV file containing email addresses"
        )

        if uploaded_file is not None:
            # File info
            file_size = uploaded_file.size / (1024 * 1024)  # Convert to MB
            st.info(f"File: {uploaded_file.name} ({file_size:.2f} MB)")

            if file_size > 50:  # Warn for large files
                st.warning("Large file detected. Processing may take some time.")

            return uploaded_file, None

        return None, "No file uploaded"

class ProgressDisplay:
    """Component for displaying batch operation progress"""

    @staticmethod
    def render(progress_data: Dict[str, Any], key_prefix: str = "progress"):
        """Render progress display"""
        st.subheader("🚀 Processing Progress")

        # Progress bar
        if progress_data['total'] > 0:
            progress_percent = progress_data['completed'] / progress_data['total']
        else:
            progress_percent = 0.0

        progress_bar = st.progress(progress_percent)

        # Metrics
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "Progress",
                f"{progress_data['completed']}/{progress_data['total']}"
            )

        with col2:
            st.metric(
                "Batches",
                f"{progress_data['current_batch']}/{progress_data['total_batches']}"
            )

        with col3:
            st.metric("Accounts Added", progress_data['accounts_added'])

        with col4:
            error_count = len(progress_data['errors'])
            st.metric("Errors", error_count)

        # Errors section
        if progress_data['errors']:
            st.error("Errors encountered:")
            for error in progress_data['errors'][-5:]:  # Show last 5 errors
                st.text(f"- {error}")

        return progress_bar

class SummaryDisplay:
    """Component for displaying operation summary"""

    @staticmethod
    def render(analysis: Dict[str, Any], campaign_info: Dict):
        """Render summary display before execution"""
        st.subheader("📊 Operation Summary")

        # Campaign info
        st.info(f"**Target Campaign:** {campaign_info.get('name', 'Unknown')} (ID: {campaign_info.get('id')})")

        # Summary metrics
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Emails to Process", analysis['total_requested'])

        with col2:
            st.metric("New to Add", analysis['total_to_add'], delta=analysis['total_to_add'])

        with col3:
            st.metric("Already in Campaign", analysis['total_already_exists'])

        # Detailed breakdown
        if analysis['to_add']:
            st.success("✅ Accounts to Add:")
            add_df = pd.DataFrame(list(analysis['to_add'].items()), columns=['Email', 'Account ID'])
            st.dataframe(add_df, use_container_width=True)

        if analysis['already_exists']:
            st.info("ℹ️ Already in Campaign:")
            existing_df = pd.DataFrame(list(analysis['already_exists'].items()), columns=['Email', 'Account ID'])
            st.dataframe(existing_df, use_container_width=True)

        if analysis['not_found']:
            st.warning("⚠️ Email Accounts Not Found:")
            for email in analysis['not_found']:
                st.text(f"- {email}")