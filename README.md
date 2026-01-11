# Clarity - Communication Data Sanitizer

A privacy-first web app that anonymizes Slack and Microsoft Teams exports by removing PII and applying SHA-256 hashing to create employee and conversation IDs.


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


## Features

- **Privacy-First**: SHA-256 salted hashing for all user and conversation IDs
- **No Text Content**: Message text is completely removed
- **No PII**: Names, emails, and identifiable information excluded
- **Timestamp Coarsening**: Timestamps rounded to nearest minute to prevent timing attacks
- **Metadata Preserved**: Reactions, threads, conversation structure maintained
- **User & Conversation ID Hashing**: All Slack IDs replaced with SHA-256 anonymized IDs
- **Bot Filtering**: Automatically excludes bots from analysis
- **Interactive Preview**: View sample data before downloading
- **Organized Output**: Messages organized by conversation and date


## How to Get Platform Exports

### Slack Export

**Permissions required**: Only Workspace Owners or Admins can export Slack data.

1. Go to your Slack workspace
2. Click workspace name → **Settings & administration** → **Workspace settings**
3. Navigate to the **Import/Export Data** page
4. Select **Export** and choose date range
5. Download the ZIP file containing users, channels, and message data

### Microsoft Teams Export

#### eDiscovery Export
**Permissions required**: eDiscovery Manager or Compliance Administrator

1. Go to [Microsoft Purview compliance portal](https://compliance.microsoft.com)
2. Navigate to **eDiscovery** → **Standard** or **Premium**
3. Create a new case or select existing case
4. Add **Search** → Define search criteria (date range, participants, keywords)
5. Once search completes, click **Export results**
6. Download the export package (includes `ExportSummary.csv`, `Users.csv`, and `Messages/` folder)
7. Extract and upload the ZIP to Clarity

**Note**: eDiscovery exports provide the most comprehensive data including:
- Message metadata (sender, timestamp, conversation ID)
- Participant information
- Channel and DM conversations
- Meeting chats (if included in search criteria)

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

1. Select platform (Slack or Microsoft Teams)
2. Upload HR CSV (Email, Department, Team, etc.) and platform export ZIP
3. Preview employee data
4. Click "Anonymize Slack Data" or "Anonymize Microsoft Teams Data"
5. Preview and download the anonymized ZIP file
6. **PASSWORD PROTECT before sharing** 
7. **DELETE LOCAL FILES after sharing**

**Sample data:** See `sample_data/HRIS.csv` and `sample_data/Slack export...` or `sample_data/teams/` in repository  
**Test at:** `http://localhost:8504`


## Local Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py --server.port 8504
```

## Output Structure

```
anonymized_export.zip
├── users.json                      # Anonymized users with SHA-256 hashed Clarity_IDs                             
│                                   # Example: {"Clarity_ID": "E8A3F2D9", "Role": "A1B2C3D4", "Team": "F6G7H8I9",
│                                   #           "Work_Location": "K1L2M3N4", "Employment_Status": "P6Q7R8S9",
│                                   #           "Employment_Type": "U1V2W3X4", "Tenure_Band": "0-3 months"}
├── conversations.json              # Conversations with SHA-256 hashed IDs
│                                   # Example: {"ConversationID": "C9A1D5E7", "Type": "channel", 
│                                   #           "Participants": "E8A3F2D9,E7B4E8A2", "MemberCount": 2}
├── filter_mappings.json            # Mapping of original filter values to hashed values
│                                   # Example: {"Team": {"Engineering": "F6G7H8I9", "Product": "A2B3C4D5"},
│                                   #           "Role": {"Engineer": "A1B2C3D4", "Manager": "B2C3D4E5"},
│                                   #           "Work_Location": {"New York": "K1L2M3N4", "Remote": "L2M3N4O5"}}
└── messages/
    ├── C9A1D5E7/                  # Hashed conversation ID (channel)
    │   ├── 2025-01-15.json        # Messages organized by date
    │   └── 2025-01-16.json
    ├── DM7B4E8A/                  # Hashed conversation ID (DM)
    │   └── 2025-01-15.json
    └── ...
```
