# Smartlead Email Campaign Manager

A Streamlit web application that allows you to add email accounts from CSV files to your Smartlead campaigns efficiently.

## 🚀 Features

- **Multi-step workflow** with clear progress tracking
- **Campaign selection** with search and filtering capabilities
- **Bulk email account processing** (handles 16k+ accounts efficiently)
- **CSV upload** with validation and error handling
- **Preview and analysis** before making changes
- **Batch processing** with progress tracking
- **Comprehensive error handling** and logging

## 📋 Prerequisites

- Python 3.8 or higher
- Smartlead account with API access
- CSV file with email addresses

## 🔧 Installation

### Option 1: Clone and Run Locally

```bash
git clone <your-repo-url>
cd smartlead-campaign-manager
pip install -r requirements.txt
streamlit run app.py
```

### Option 2: Deploy to Streamlit Cloud

1. Fork this repository
2. Go to [Streamlit Cloud](https://share.streamlit.io/)
3. Click "New app" and connect your repository
4. Configure environment variables in Streamlit Cloud settings
5. Deploy!

### Option 3: Using the Setup Script

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

## ⚙️ Configuration

### Environment Variables

Set these in Streamlit Cloud or create a `.env` file locally:

```bash
SMARTLEAD_API_KEY=your_api_key_here
APP_PASSWORD=strong_password_for_app_access
BATCH_SIZE=50
MAX_FILE_SIZE_MB=200
LOG_LEVEL=INFO
EMAIL_FETCH_FAST_MODE=true
EMAIL_FETCH_CONCURRENCY=30
EMAIL_FETCH_EXPECTED_ACCOUNTS=30000
EMAIL_FETCH_OVERFETCH_MULTIPLIER=1.25
EMAIL_FETCH_CAMPAIGNS=false
ACCOUNT_LOOKUP_FALLBACK_ENABLED=true
ACCOUNT_LOOKUP_CONCURRENCY=20
SLINBOXES_LOOKUP_BASE_URL=https://slinboxes.eagleinfoservice.com/api
```

**Security note:** The app requires `APP_PASSWORD` to be defined in `st.secrets` (or `.streamlit/secrets.toml` for Streamlit Cloud). If the secret is missing or the entered password is incorrect, the application will stop and display a clear error so deployments fail fast rather than running unprotected.


### Fast Email Account Fetching

The app fetches Smartlead email-account pages concurrently by default so large accounts do not wait on 60+ serial page requests. Tune `EMAIL_FETCH_CONCURRENCY`, `EMAIL_FETCH_EXPECTED_ACCOUNTS`, and `EMAIL_FETCH_OVERFETCH_MULTIPLIER` if your workspace size or Smartlead rate limits change. Set `EMAIL_FETCH_FAST_MODE=false` to fall back to conservative sequential pagination.

If an uploaded email is not present in the bulk Smartlead fetch, the app can query `SLINBOXES_LOOKUP_BASE_URL` via `/accounts/lookup?email=...` as a single-account fallback before marking the email as not found. Disable this with `ACCOUNT_LOOKUP_FALLBACK_ENABLED=false`.

### Getting Your Smartlead API Key

1. Log in to your Smartlead account
2. Navigate to Settings → API Keys
3. Generate a new API key
4. Copy the key and add it to your environment variables

## 📖 Usage

### Step 1: Enter API Key
- Enter your Smartlead API key in the sidebar
- The app will validate the key and fetch your campaigns

### Step 2: Select Campaign
- Browse and search through your available campaigns
- Filter by status (Active, Paused, etc.)
- View campaign details before selection
- Click "Next Step" to continue

### Step 3: Fetch Email Accounts
- Click the mandatory "Fetch All Email Accounts" button
- Wait for all your email accounts to be retrieved (may take time for large accounts)
- View account statistics and types

### Step 4: Upload CSV
- Upload a CSV file containing email addresses
- The CSV must have an 'email' column
- Other columns are ignored
- View sample emails found in the file

### Step 5: Map and Preview
- Click "Map Emails to Accounts" to find matching accounts
- Review the analysis:
  - Emails that will be added to the campaign
  - Emails already in the campaign
  - Emails not found in your account

### Step 6: Execute Changes
- Review the final summary
- Click "Execute Changes" to add accounts
- Monitor batch processing progress
- View results and error messages

## 📁 CSV Format

Your CSV file should contain emails in a column named 'email' (case-insensitive):

```csv
email,name,company,role
john@example.com,John Doe,Acme Corp,Engineer
jane@test.com,Jane Smith,Tech Inc,Manager
```

**Valid email column names:** `email`, `Email`, `EMAIL`, `email_address`, `emailaddress`

## 🚨 Error Handling

The app includes comprehensive error handling for:
- Invalid API keys
- Network connectivity issues
- Malformed CSV files
- Invalid email addresses
- API rate limiting
- Missing email accounts

## 🔍 Troubleshooting

### Common Issues

**"Failed to fetch campaigns"**
- Verify your API key is correct
- Check your internet connection
- Ensure your Smartlead account is active

**"No email column found in CSV"**
- Ensure your CSV has an 'email' column
- Check spelling and case sensitivity
- Make sure the file is saved as CSV format

**"Email account not found"**
- Verify the email exists in your Smartlead account
- Check for typos in the email addresses
- Ensure the email accounts are properly configured in Smartlead

**Processing is slow**
- Large account lists (16k+) take time to fetch
- Batch processing helps but may still take time
- Monitor progress bars for real-time updates

## 📊 Performance

The application is optimized for:
- **Memory efficiency**: Processes large datasets without memory issues
- **API rate limiting**: Respects Smartlead API limits with exponential backoff
- **Batch processing**: Adds accounts in batches of 50 by default
- **Progress tracking**: Real-time feedback during long operations

## 🔧 Development

### Running Tests

```bash
pytest tests/ -v
```

### Project Structure

```
smartlead-campaign-manager/
├── app.py                    # Main Streamlit application
├── requirements.txt          # Python dependencies
├── .env.example             # Environment variables template
├── src/
│   ├── __init__.py
│   ├── api_client.py        # Smartlead API client
│   ├── data_processor.py    # CSV and data processing
│   └── ui_components.py     # Reusable UI components
├── tests/
│   ├── __init__.py
│   ├── test_api_client.py
│   ├── test_data_processor.py
│   ├── test_ui_components.py
│   └── test_app.py
├── docs/
│   └── DEPLOYMENT.md
├── scripts/
│   └── setup.sh
└── data/
    └── sample_input.csv     # Sample CSV file
```

## 🚀 Deployment

### Streamlit Cloud (Recommended)

1. Push your code to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io/)
3. Connect your repository
4. Configure environment variables
5. Deploy!

### Docker

```bash
docker build -t smartlead-manager .
docker run -p 8501:8501 --env-file .env smartlead-manager
```

For detailed deployment instructions, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Support

For support:
1. Check the troubleshooting section above
2. Review the [Smartlead API documentation](https://docs.smartlead.ai/)
3. Create an issue in this repository
4. Contact Smartlead support for API-specific issues