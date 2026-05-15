import pandas as pd
from collections import defaultdict
from zipfile import ZipFile
import csv
from io import StringIO
from utils.hashing import salted_hash
from utils.file_helpers import round_timestamp
import re

EMAIL_REGEX = r'[\w\.-]+@[\w\.-]+'

def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default

def decode_bytes(b):
    try:
        return b.decode('utf-8-sig')
    except Exception:
        try:
            return b.decode('utf-8', errors='replace')
        except Exception:
            return b.decode('latin-1', errors='replace')

def normalize_recipients(recipients):
    if not recipients:
        return []
    # Try to extract emails with regex first
    emails = re.findall(EMAIL_REGEX, recipients.lower())
    if emails:
        return list({e.strip() for e in emails})
    # fallback split on common separators
    parts = re.split(r'[;,|]', recipients)
    return [p.strip().lower() for p in parts if p and '@' in p]

def parse_date_str(date_str):
    if not date_str:
        return None, None
    try:
        dt = pd.to_datetime(date_str, errors='coerce', utc=True)
        if pd.isna(dt):
            return None, None
        date_only = dt.strftime('%Y-%m-%d')
        iso_ts = dt.isoformat()
        return date_only, iso_ts
    except Exception:
        # best-effort fallback
        try:
            if 'T' in date_str:
                return date_str.split('T')[0], date_str
            return date_str.split(' ')[0], date_str
        except Exception:
            return None, date_str

def parse_teams_export(zip_uploaded_file, employee_data, bot_ids, salt):
    """
    Parse and anonymize Microsoft Teams eDiscovery export data.

    Args:
        zip_uploaded_file: Uploaded ZIP file (path or file-like)
        employee_data: DataFrame with employee information (must have 'email' column)
        bot_ids: list of bot user IDs/emails (normalized lowercase)
        salt: salt for hashing

    Returns:
        dict: Anonymized output with users, conversations, messages, and filter_mappings
    """
    # Initialize filter mappings storage
    filter_mappings = {
        "Team": {},
        "Role": {},
        "Work_Location": {},
        "Employment_Status": {},
        "Employment_Type": {},
        "Tenure_Band": {},
        "Timezone": {}
    }

    # Create email-to-hash mapping
    email_hashes = {}
    for _, row in employee_data.iterrows():
        email = (row.get("Email") or row.get("email") or "").strip()
        if not email:
            continue

        salted_clarity_id = "E" + salted_hash(email, salt)

        # Hash HRIS fields and store mappings
        hashed_fields = {}
        for field in ["Team", "Role", "Work_Location", "Employment_Status", "Employment_Type", "Tenure_Band", "timezone"]:
            if field in row and pd.notna(row[field]):
                original_value = str(row[field])
                hashed_value = salted_hash(original_value, salt)
                mapping_key = "Timezone" if field == "timezone" else field
                # only add mapping once (preserve deterministic mapping)
                if original_value not in filter_mappings[mapping_key]:
                    filter_mappings[mapping_key][original_value] = hashed_value
                hashed_fields[field] = hashed_value
            else:
                hashed_fields[field] = None

        email_hashes[email.lower()] = {
            "Clarity_ID": salted_clarity_id,
            "Team": hashed_fields.get("Team"),
            "Role": hashed_fields.get("Role"),
            "Timezone": hashed_fields.get("timezone"),
            "Work_Location": hashed_fields.get("Work_Location"),
            "Employment_Status": hashed_fields.get("Employment_Status"),
            "Employment_Type": hashed_fields.get("Employment_Type"),
            "Tenure_Band": hashed_fields.get("Tenure_Band"),
        }

    output = {
        "users": [],
        "conversations": [],
        "messages": defaultdict(lambda: defaultdict(list)),
        "filter_mappings": filter_mappings
    }

    seen_messages = set()
    conversations_seen = set()

    with ZipFile(zip_uploaded_file, 'r') as zip_ref:
        file_list = zip_ref.namelist()

        # find users csv (case-insensitive endswith)
        users_csv = next((f for f in file_list if f.lower().endswith('users.csv')), None)
        if users_csv:
            users_content = decode_bytes(zip_ref.read(users_csv))
            users_reader = csv.DictReader(StringIO(users_content))
            for user in users_reader:
                email = (user.get('Email') or user.get('email') or '').strip().lower()
                if not email or email in (id_.lower() for id_ in bot_ids):
                    continue
                if email in email_hashes:
                    emp_data = email_hashes[email]
                    output["users"].append({
                        "Clarity_ID": emp_data["Clarity_ID"],
                        "Team": emp_data["Team"],
                        "Role": emp_data["Role"],
                        "Timezone": emp_data["Timezone"],
                        "Work_Location": emp_data["Work_Location"],
                        "Employment_Status": emp_data["Employment_Status"],
                        "Employment_Type": emp_data["Employment_Type"],
                        "Tenure_Band": emp_data["Tenure_Band"]
                    })

        # find summary-like CSVs (support multiple possible filenames)
        summary_candidates = [f for f in file_list if 'summary' in f.lower() or f.lower().endswith('exportsummary.csv') or f.lower().endswith('messages.csv') or 'message' in f.lower()]
        for summary_csv in summary_candidates:
            try:
                content = decode_bytes(zip_ref.read(summary_csv))
            except Exception:
                continue

            # try to parse as CSV; skip if no header
            try:
                reader = csv.DictReader(StringIO(content))
            except Exception:
                continue

            for row in reader:
                item_type = (row.get('Type') or row.get('MessageType') or '').strip()
                sender_email = (row.get('Sender') or row.get('From') or row.get('FromAddress') or '').strip().lower()
                recipients_raw = row.get('Recipients') or row.get('To') or row.get('RecipientsList') or ''
                recipients = normalize_recipients(recipients_raw)
                conversation_id = row.get('ConversationId') or row.get('ConversationId') or row.get('Id') or row.get('ThreadId') or ''
                subject = row.get('Subject') or row.get('Title') or ''
                date_sent_raw = row.get('DateSent') or row.get('Date') or row.get('Timestamp') or ''

                # skip system or bot senders
                if not sender_email or sender_email in (id_.lower() for id_ in bot_ids):
                    continue

                # skip senders not in employee list
                if sender_email not in email_hashes:
                    # allow external participants as anonymous if needed; skip for now
                    continue

                # ensure conversation id exists
                if not conversation_id:
                    conversation_id = f"{sender_email}_{subject[:50]}_{date_sent_raw}"

                hashed_conv_id = "C" + salted_hash(conversation_id, salt)

                # dedupe conversation creation
                if hashed_conv_id not in conversations_seen:
                    conversations_seen.add(hashed_conv_id)

                    # include sender + recipients (only those in company HRIS)
                    participant_emails = set([e for e in recipients if e in email_hashes])
                    participant_emails.add(sender_email)
                    mapped_participants = [email_hashes[e]["Clarity_ID"] for e in participant_emails if e in email_hashes]

                    # determine conversation type more robustly
                    conv_type = "chat"
                    thread_type = (row.get('ThreadType') or row.get('ConversationType') or '').lower()
                    if thread_type and 'channel' in thread_type:
                        conv_type = 'channel'
                    elif 'channelname' in ''.join(row.keys()).lower() or row.get('Channel') or row.get('TeamName'):
                        conv_type = 'channel'
                    elif len(mapped_participants) > 2:
                        conv_type = 'group_chat'
                    else:
                        conv_type = 'chat'

                    output["conversations"].append({
                        "ConversationID": hashed_conv_id,
                        "Type": conv_type,
                        "Participants": ",".join(mapped_participants),
                        "MemberCount": len(mapped_participants)
                    })

                # prepare message entry and deduplicate
                date_only, iso_ts = parse_date_str(date_sent_raw)
                timestamp_for_round = iso_ts or date_sent_raw
                msg_key = (hashed_conv_id, sender_email, iso_ts or date_only or '', row.get('MessageId') or row.get('Id') or subject[:40])
                if msg_key in seen_messages:
                    continue
                seen_messages.add(msg_key)

                output["messages"][hashed_conv_id][date_only or 'unknown'].append({
                    "Clarity_ID": email_hashes[sender_email]["Clarity_ID"],
                    "Timestamp": round_timestamp(timestamp_for_round, round_to_minutes=1) if timestamp_for_round else None,
                    "Has_Reactions": row.get('HasReactions', '').lower() == 'true',
                    "Reaction_Count": safe_int(row.get('ReactionCount') or row.get('Reaction_Count') or 0, 0),
                    "Has_Attachments": (row.get('HasAttachments', '').lower() == 'true') or safe_int(row.get('AttachmentCount') or row.get('Attachment_Count') or 0, 0) > 0,
                    "Attachment_Count": safe_int(row.get('AttachmentCount') or row.get('Attachment_Count') or 0, 0),
                    "Is_Threaded": bool(row.get('ParentMessageId') or row.get('ThreadId')),
                })

    # Convert defaultdicts to plain dicts for JSON serialization
    messages_out = {}
    for conv_id, days in output["messages"].items():
        messages_out[conv_id] = {day: msgs for day, msgs in days.items()}

    output["messages"] = messages_out

    return output
