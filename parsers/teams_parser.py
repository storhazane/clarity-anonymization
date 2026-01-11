"""Microsoft Teams export parser."""
import pandas as pd
from collections import defaultdict
from zipfile import ZipFile
import csv
from io import StringIO
from utils.hashing import salted_hash
from utils.file_helpers import round_timestamp


def parse_teams_export(zip_uploaded_file, employee_data, bot_ids, salt):
    """
    Parse and anonymize Microsoft Teams eDiscovery export data.
    
    Args:
        zip_uploaded_file: Uploaded ZIP file
        employee_data: DataFrame with employee information (must have 'email' column)
        bot_ids: List of bot user IDs/emails
        salt: Salt for hashing
        
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
        email = row.get("Email") or row.get("email", "")
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

    with ZipFile(zip_uploaded_file, 'r') as zip_ref:
        file_list = zip_ref.namelist()
        
        # Process Users.csv
        users_csv = next((f for f in file_list if f.endswith('Users.csv')), None)
        if users_csv:
            users_content = zip_ref.read(users_csv).decode('utf-8')
            users_reader = csv.DictReader(StringIO(users_content))
            
            for user in users_reader:
                email = user.get('Email', '').lower()
                
                if email in bot_ids or not email:
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
            })        # Process ExportSummary.csv for conversations and messages
        summary_csv = next((f for f in file_list if f.endswith('ExportSummary.csv')), None)
        if summary_csv:
            summary_content = zip_ref.read(summary_csv).decode('utf-8')
            summary_reader = csv.DictReader(StringIO(summary_content))
            
            conversations_seen = set()
            
            for row in summary_reader:
                item_type = row.get('Type', '')
                sender_email = row.get('Sender', '').lower()
                recipients = row.get('Recipients', '')
                conversation_id = row.get('ConversationId', row.get('Id', ''))
                subject = row.get('Subject', '')
                date_sent = row.get('DateSent', row.get('Date', ''))
                
                # Skip if sender not in our employee list
                if sender_email not in email_hashes:
                    continue
                
                # Create hashed conversation ID
                hashed_conv_id = "C" + salted_hash(conversation_id, salt)
                
                # Add conversation if not seen
                if hashed_conv_id not in conversations_seen:
                    conversations_seen.add(hashed_conv_id)
                    
                    # Parse participants
                    participant_emails = [e.strip().lower() for e in recipients.split(';') if e.strip()]
                    participant_emails.append(sender_email)
                    
                    mapped_participants = [
                        email_hashes[email]["Clarity_ID"]
                        for email in set(participant_emails)
                        if email in email_hashes
                    ]
                    
                    conv_type = "chat" if "IM" in item_type or len(mapped_participants) <= 2 else "channel"
                    
                    output["conversations"].append({
                        "ConversationID": hashed_conv_id,
                        "Type": conv_type,
                        "Participants": ",".join(mapped_participants),
                        "MemberCount": len(mapped_participants)
                    })
                
                # Add message
                if date_sent:
                    try:
                        msg_date = date_sent.split('T')[0] if 'T' in date_sent else date_sent.split(' ')[0]
                    except:
                        msg_date = "unknown"
                    
                    output["messages"][hashed_conv_id][msg_date].append({
                        "Clarity_ID": email_hashes[sender_email]["Clarity_ID"],
                        "Timestamp": round_timestamp(date_sent, round_to_minutes=1),
                        "Has_Reactions": False,  # Not typically in eDiscovery export
                        "Reaction_Count": 0,
                        "Has_Attachments": row.get('HasAttachments', '').lower() == 'true',
                        "Attachment_Count": int(row.get('AttachmentCount', 0)) if row.get('AttachmentCount') else 0,
                        "Is_Threaded": False,  # Would need message threading info
                    })

    return output