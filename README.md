# PII Sanitizer (Microsoft Presidio + Streamlit)

A tiny web app that uses [Microsoft Presidio](https://microsoft.github.io/presidio/) to detect and anonymize PII in CSV files (e.g. Slack exports) and return a cleaned CSV.


## Features

- **Privacy-First**: K-anonymity (k=5) applied to all employee fields (Role, Team, Work_Location, Employment_Status, Employment_Type, Tenure_Band)
  - Strict enforcement for Role and Team: If "Others" < 5, entire column becomes "Others"
  - Flexible enforcement for other fields: If "Others" < 5, values are still grouped as "Others" but kept
- **No Text Content**: Message text is completely removed
- **No PII**: Names, emails, and identifiable information excluded
- **Timestamp Coarsening**: Timestamps rounded to nearest minute to prevent timing attacks
- **Metadata Preserved**: Reactions, threads, conversation structure maintained
- **User & Conversation ID Hashing**: All Slack IDs replaced with SHA-256 anonymized IDs
- **Bot Filtering**: Automatically excludes bots from analysis
- **Interactive Preview**: View sample data before downloading
- **Organized Output**: Messages organized by conversation and date


## How to Get a Slack Export

**Permissions required**: Only Workspace Owners or Admins can export Slack data.

1. Go to your Slack workspace
2. Click workspace name → **Settings & administration** → **Workspace settings**
3. Navigate to the **Import/Export Data** page
4. Select **Export** and choose date range
5. Download the ZIP file containing users, channels, and message data

###  Before Sharing the Anonymized Export

Even though the export is anonymized, **you MUST password-protect the ZIP file** before uploading to Google Drive, Dropbox, or any cloud storage.

**Why?** Anyone with access to your organization's HRIS data can reverse-engineer the Clarity_IDs by matching Department and Team combinations. The anonymization only protects against external threats, not internal analysis.

**How to password protect:**
```bash
# On macOS/Linux
zip -e -r protected_export.zip anonymized_slack_export.zip

# On Windows (PowerShell)
Compress-Archive -Path anonymized_slack_export.zip -DestinationPath protected_export.zip
# Then right-click → Properties → Advanced → Encrypt contents
```


## Usage & Testing

1. Upload HR CSV (Email, Department, Team) and Slack Export ZIP
2. Preview employee data with k-anonymity applied
3. Click "Anonymize Slack Data"
4. Preview and download the anonymized ZIP file
5. **PASSWORD PROTECT before sharing** 
6. **DELETE LOCAL FILES after sharing**

**Sample data:** See `sample_data/HRIS.csv` in repository for CSV structure  
**Test at:** `http://localhost:8504`


## Local Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install streamlit pandas numpy

# Run the app
streamlit run app.py --server.port 8504

```


## Before & After Examples

### BEFORE (Non-Sanitized Slack Message)

```json
{
  "user": "U024BE7LH",
  "type": "message",
  "ts": "1700000012.789456",
  "text": "Hey everyone, Emma Wilson will join Product team starting Monday!",
  "user_profile": {
    "real_name": "Emma Wilson",
    "email": "emma.wilson@example.com",
    "avatar_hash": "a5bb22f39",
    "image_512": "https://avatars.slack-edge.com/2023-01-01/abc512.png"
  },
  "reactions": [
    {
      "name": "thumbsup",
      "count": 3,
      "users": ["U024BE7LH", "U7812KD91", "U3819PQM1"]
    }
  ],
  "thread_ts": "1700000012.789456",
  "reply_count": 5,
  "reply_users": ["U024BE7LH", "U7812KD91"],
  "latest_reply": "1700003712.123456",
  "edited": {
    "user": "U024BE7LH",
    "ts": "1700000025.000000"
  }
}
```

### AFTER (Sanitized Output)

```json
{
  "user": "E8A3F2D9C1",
  "ts": "1700000012",
  "edited": {
    "user": "E8A3F2D9C1",
    "ts": "1700000024"
  },
  "thread_ts": "1700000012",
  "reply_count": 5,
  "reply_users_count": 2,
  "reply_users": ["E8A3F2D9C1", "E7B4E8A2F3"],
  "latest_reply": "1700003712",
  "reactions": [
    {
      "count": 3,
      "users": ["E8A3F2D9C1", "E7B4E8A2F3", "E9A1D5E7B2"]
    }
  ]
}
```


## Output Structure

```
anonymized_slack_export.zip
├── users.json                      # Anonymized users with SHA-256 hashed Clarity_IDs
│                                   # K-anonymity (k=5) applied to all fields: Role, Team, Work_Location,
│                                   # Employment_Status, Employment_Type, Tenure_Band
│                                   # Example: {"Clarity_ID": "E8A3F2D9C1", "Role": "Others", "Team": "Team_Alpha",
│                                   #           "Work_Location": "Amsterdam", "Employment_Status": "Active"}
├── conversations.json              # Conversations with SHA-256 hashed IDs
│                                   # Example: {"ConversationID": "C9A1D5E7B2", "Type": "channel", "Participants": "E8A3F2D9C1,E7B4E8A2F3"}
└── messages/
    ├── C9A1D5E7B2/                # Hashed conversation ID (channel)
    │   ├── 2025-01-15.json        # Messages organized by date
    │   └── 2025-01-16.json
    ├── D7B4E8A2F3/                # Hashed conversation ID (DM)
    │   └── 2025-01-15.json
    └── ...
```
