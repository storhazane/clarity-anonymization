"""Slack export parser."""
import pandas as pd
from collections import defaultdict
from utils.hashing import salted_hash
from utils.file_helpers import safe_json_read, round_timestamp
from utils.platform_detection import get_file_from_zip


def parse_slack_export(zip_uploaded_file, employee_data, bot_ids, salt):
    """
    Parse and anonymize Slack export data.
    
    Args:
        zip_uploaded_file: Uploaded ZIP file
        employee_data: DataFrame with employee information
        bot_ids: List of bot user IDs
        salt: Salt for hashing
        
    Returns:
        dict: Anonymized output with users, conversations, messages, and filter_mappings
    """
    from zipfile import ZipFile
    import json
    
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

    # Create employee hashes with filter mappings
    employee_hashes = {}
    for _, row in employee_data.iterrows():
        slack_id = str(row["slack_id"]) if pd.notna(row["slack_id"]) else None
        if not slack_id or slack_id == 'nan':
            continue
            
        salted_clarity_id = "E" + salted_hash(slack_id, salt)
        
        # Hash HRIS fields and store mappings
        hashed_fields = {}
        for field in ["Team", "Role", "Work_Location", "Employment_Status", "Employment_Type", "Tenure_Band", "timezone"]:
            if field in row and pd.notna(row[field]):
                original_value = str(row[field])
                hashed_value = salted_hash(original_value, salt)
                
                # Store mapping (original -> hashed)
                mapping_key = "Timezone" if field == "timezone" else field
                filter_mappings[mapping_key][original_value] = hashed_value
                hashed_fields[field] = hashed_value
            else:
                hashed_fields[field] = None

        employee_hashes[slack_id] = {
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
        # Filter out __MACOSX files
        clean_files = [f for f in file_list if not f.startswith('__MACOSX')]
        
        # Process users
        users_file = get_file_from_zip(zip_ref, 'users.json')
        if users_file:
            users_data = safe_json_read(zip_ref, users_file)
            for user in users_data:
                user_id = user.get('id', '')
                
                if user_id in bot_ids:
                    continue
                
                if user_id in employee_hashes:
                    emp_data = employee_hashes[user_id]
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
        
        # Load all conversation metadata files
        channels = []
        groups = []
        dms = []
        mpims = []
        
        channels_file = get_file_from_zip(zip_ref, 'channels.json')
        if channels_file:
            channels = safe_json_read(zip_ref, channels_file)
        
        groups_file = get_file_from_zip(zip_ref, 'groups.json')
        if groups_file:
            groups = safe_json_read(zip_ref, groups_file)
            
        dms_file = get_file_from_zip(zip_ref, 'dms.json')
        if dms_file:
            dms = safe_json_read(zip_ref, dms_file)
            
        mpims_file = get_file_from_zip(zip_ref, 'mpims.json')
        if mpims_file:
            mpims = safe_json_read(zip_ref, mpims_file)
        
        # Process all conversations
        conv_meta_list = dms + mpims + channels + groups
        conv_id_map = {}  # Map folder names to conversation IDs
        
        for conv in conv_meta_list:
            members = [
                employee_hashes.get(m, {}).get("Clarity_ID")
                for m in conv.get("members", [])
                if employee_hashes.get(m) and m not in bot_ids
            ]
            
            if not members:
                continue
            
            is_dm = len(members) <= 3 or conv.get("is_im") or conv.get("is_mpim")
            
            # Get original conversation ID or name
            original_conv_id = conv.get("id", conv.get("name", ""))
            conv_type = "dm" if is_dm else "channel"
            
            # Create hashed conversation ID
            prefix = "DM" if is_dm else "C"
            conv_id = prefix + salted_hash(original_conv_id, salt)
            
            # Map folder name to conversation ID
            conv_name = conv.get("name", conv.get("id", ""))
            conv_id_map[conv_name] = conv_id
            
            # Add conversation
            output["conversations"].append({
                "ConversationID": conv_id,
                "Type": conv_type,
                "Participants": ",".join(sorted(members)),
                "MemberCount": len(members)
            })
        
        # Process messages from folders
        folders = [f for f in clean_files if f.endswith("/") and '__MACOSX' not in f]
        
        for folder in folders:
            folder_name = folder.strip("/").split("/")[-1]
            conv_id = conv_id_map.get(folder_name)
            
            if not conv_id:
                continue
            
            # Find all message files in this folder
            for file in clean_files:
                if file.startswith(folder) and file.endswith(".json") and '__MACOSX' not in file:
                    try:
                        # Extract date from filename
                        date = file.split('/')[-1].replace('.json', '')
                        
                        messages = safe_json_read(zip_ref, file)
                        
                        if not messages or not isinstance(messages, list):
                            continue
                        
                        for msg in messages:
                            if not isinstance(msg, dict):
                                continue
                            
                            user_id = msg.get("user")
                            if not user_id or user_id in bot_ids:
                                continue
                            
                            clarity = employee_hashes.get(user_id, {}).get("Clarity_ID")
                            if not clarity:
                                continue
                            
                            # Build sanitized message
                            sanitized_msg = {
                                "user": clarity,
                                "ts": round_timestamp(msg.get('ts', ''), round_to_minutes=1)
                            }
                            
                            # Add edited info if present
                            if 'edited' in msg:
                                edited_user = msg['edited'].get('user')
                                sanitized_msg["edited"] = {
                                    "user": employee_hashes.get(edited_user, {}).get("Clarity_ID", edited_user) if edited_user else clarity,
                                    "ts": round_timestamp(msg['edited'].get('ts', ''), round_to_minutes=1)
                                }
                            
                            # Add threading info
                            if 'thread_ts' in msg:
                                sanitized_msg["thread_ts"] = round_timestamp(msg.get('thread_ts', ''), round_to_minutes=1)
                            
                            if 'reply_count' in msg:
                                sanitized_msg["reply_count"] = msg['reply_count']
                            
                            if 'reply_users' in msg:
                                reply_users = [
                                    employee_hashes[uid]["Clarity_ID"]
                                    for uid in msg['reply_users']
                                    if uid in employee_hashes
                                ]
                                sanitized_msg["reply_users_count"] = len(reply_users)
                                sanitized_msg["reply_users"] = reply_users
                            
                            if 'latest_reply' in msg:
                                sanitized_msg["latest_reply"] = round_timestamp(msg.get('latest_reply', ''), round_to_minutes=1)
                            
                            # Process reactions
                            if 'reactions' in msg:
                                sanitized_reactions = []
                                for reaction in msg['reactions']:
                                    reactor_users = [
                                        employee_hashes[uid]["Clarity_ID"]
                                        for uid in reaction.get('users', [])
                                        if uid in employee_hashes
                                    ]
                                    if reactor_users:
                                        sanitized_reactions.append({
                                            "count": len(reactor_users),
                                            "users": reactor_users
                                        })
                                
                                if sanitized_reactions:
                                    sanitized_msg["reactions"] = sanitized_reactions
                            
                            output["messages"][conv_id][date].append(sanitized_msg)
                    except:
                        continue

    return output