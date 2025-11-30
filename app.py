import io
import streamlit as st
import numpy as np
import pandas as pd
import json
import csv
import re
import hashlib
from datetime import datetime
from zipfile import ZipFile


def safe_json_read(zip_obj, file_path):
    content = zip_obj.open(file_path).read()
    for encoding in ['utf-8', 'latin-1', 'cp1252']:
        try:
            if isinstance(content, bytes):
                decoded = content.decode(encoding)
            else:
                decoded = content
            return json.loads(decoded)
        except Exception:
            continue

    # Sanitized error - don't expose file paths
    raise ValueError("Unable to read JSON file from Slack export. File may be corrupted or in an unexpected format.")


def detect_delimiter(file):
    file.seek(0)
    sample = file.read(4096)
    file.seek(0)
    if isinstance(sample, bytes):
        sample = sample.decode('utf-8', errors='ignore')
    try:
        sniffer = csv.Sniffer()
        return sniffer.sniff(sample).delimiter
    except:
        return ','


def round_timestamp(ts_string, round_to_minutes=1):
    try:
        ts_float = float(ts_string)
        dt = datetime.fromtimestamp(ts_float)
        # Round to nearest minute (remove seconds and microseconds)
        rounded_dt = dt.replace(second=0, microsecond=0)
        # Return as integer timestamp (no milliseconds)
        return str(int(rounded_dt.timestamp()))
    except:
        return ts_string


def apply_k_anonymity(df, column, k=5, enforce_strict=True):
    if column not in df.columns:
        return df
    
    # First, replace any missing/null/empty values with "Others"
    df_modified = df.copy()
    df_modified[column] = df_modified[column].fillna("Others")
    df_modified[column] = df_modified[column].apply(lambda x: "Others" if x == "" or pd.isna(x) else x)
    
    # Count occurrences of each value
    value_counts = df_modified[column].value_counts()
    
    # Replace values with count < k with "Others"
    df_modified[column] = df_modified[column].apply(lambda x: "Others" if value_counts.get(x, 0) < k else x)
    
    # Check if "Others" itself has < k occurrences (only enforce for strict fields)
    if enforce_strict:
        others_count = (df_modified[column] == "Others").sum()
        if others_count > 0 and others_count < k:
            # Replace entire column with "Others" (only for critical fields like Role/Team)
            df_modified[column] = "Others"
    
    return df_modified


def combine_data(uploaded_file, zip_uploaded_file):
    delimiter = detect_delimiter(uploaded_file)
    df = pd.read_csv(uploaded_file, delimiter=delimiter)

    with ZipFile(zip_uploaded_file, 'r') as zip_object:
        file_list = zip_object.namelist()

        users_json_path = next((f for f in file_list if f.endswith("users.json") and '__MACOSX' not in f), None)
        if not users_json_path:
            raise ValueError("Slack export is missing required user data. Please ensure you've exported a complete Slack workspace.")

        slack_user_data = safe_json_read(zip_object, users_json_path)
        
        # Check if this is already anonymized data
        if slack_user_data and isinstance(slack_user_data, list) and slack_user_data[0].get('Clarity_ID'):
            raise ValueError("This appears to be an already anonymized Slack export. Please upload the original Slack export ZIP file.")

        slack_user_data = pd.DataFrame([{
            "slack_id": u["id"],
            "email_address": u["profile"].get("email"),
            "timezone": u.get("tz_label"),
            "is_bot": u["profile"].get("bot_id") is not None or u.get("is_bot", False)
        } for u in slack_user_data if isinstance(u, dict) and u.get("id")])

    email_col = next((c for c in ["Email Address", "email", "Email", "work_email", "Email"] if c in df.columns), None)
    
    if not email_col:
        raise ValueError("HRIS file must contain an email column. Accepted names: 'Email', 'Email Address', 'email', or 'work_email'")

    merged = slack_user_data.merge(df, how="outer", left_on="email_address", right_on=email_col)

    # Separate bots and real users
    employee_data = merged[merged.is_bot == False].copy()
    bot_ids = merged[merged.is_bot == True].slack_id.tolist()
    
    # Find users in Slack but not in HRIS (excluding bots)
    slack_only_users = employee_data[employee_data[email_col].isna()].copy()
    if len(slack_only_users) > 0:
        unmapped_emails = slack_only_users['email_address'].dropna().tolist()
        unmapped_count = len(unmapped_emails)
        sample_emails = unmapped_emails[:5]
        
        error_msg = f"Found {unmapped_count} Slack user(s) that cannot be mapped to HRIS data.\n\n"
        error_msg += "Sample unmapped emails:\n"
        for email in sample_emails:
            error_msg += f"  • {email}\n"
        if unmapped_count > 5:
            error_msg += f"  ... and {unmapped_count - 5} more\n"
        error_msg += "\nPlease ensure all Slack users (except bots) exist in your HRIS CSV file."
        raise ValueError(error_msg)
    
    # Find users in HRIS but not in Slack (warning, not error)
    hris_only_users = employee_data[employee_data['slack_id'].isna()].copy()
    if len(hris_only_users) > 0:
        st.warning(f" {len(hris_only_users)} employee(s) in HRIS were not found in Slack export. They will be excluded from the anonymized data.")

    # Keep only successfully mapped users
    employee_data = employee_data[employee_data['slack_id'].notna() & employee_data[email_col].notna()].copy()
    
    if len(employee_data) == 0:
        raise ValueError("No users could be matched between Slack export and HRIS data. Please check that emails match in both files.")

    # Use one-way hashing (SHA-256) to generate Clarity_IDs - no reverse lookup possible
    def generate_clarity_id(slack_id):
        hash_object = hashlib.sha256(slack_id.encode())
        hash_hex = hash_object.hexdigest()
        # Take first 10 chars and prepend 'E' for employee
        return "E" + hash_hex[:10].upper()
    
    employee_data["Clarity_ID"] = employee_data["slack_id"].apply(generate_clarity_id)

    # Calculate Tenure_Band from Date_of_Hire if available
    if "Date_of_Hire" in employee_data.columns:
        def calculate_tenure_band(hire_date):
            if pd.isna(hire_date):
                return "Unknown"
            try:
                hire_dt = pd.to_datetime(hire_date)
                tenure_days = (datetime.now() - hire_dt).days
                
                if tenure_days < 90:
                    return "0-3mo"
                elif tenure_days < 180:
                    return "3-6mo"
                elif tenure_days < 365:
                    return "6-12mo"
                elif tenure_days < 730:
                    return "1-2yr"
                elif tenure_days < 1825:
                    return "2-5yr"
                else:
                    return "5+yr"
            except:
                return "Unknown"
        
        employee_data["Tenure_Band"] = employee_data["Date_of_Hire"].apply(calculate_tenure_band)

    # Apply k-anonymity to all fields
    # Strict enforcement (replace all with "Others" if "Others" < k) only for Role and Team
    strict_fields = ["Role", "Team"]
    optional_fields = ["Work_Location", "Employment_Status", "Employment_Type", "Tenure_Band"]
    
    for field in strict_fields:
        if field in employee_data.columns:
            employee_data = apply_k_anonymity(employee_data, field, k=5, enforce_strict=True)
    
    for field in optional_fields:
        if field in employee_data.columns:
            employee_data = apply_k_anonymity(employee_data, field, k=5, enforce_strict=False)

    return employee_data, bot_ids


def extract_zip_files(zip_uploaded_file, employee_data, list_of_bots_ids):
    from collections import defaultdict
    import os

    employee_hashes = {}
    for _, row in employee_data.iterrows():
        employee_hashes[row["slack_id"]] = {
            "Clarity_ID": row["Clarity_ID"],
            "Team": row.get("Team") if "Team" in row else None,
            "Role": row.get("Role") if "Role" in row else None,
            "Timezone": row.get("timezone") if "timezone" in row else None,
            "Work_Location": row.get("Work_Location") if "Work_Location" in row else None,
            "Employment_Status": row.get("Employment_Status") if "Employment_Status" in row else None,
            "Employment_Type": row.get("Employment_Type") if "Employment_Type" in row else None,
            "Tenure_Band": row.get("Tenure_Band") if "Tenure_Band" in row else None,
        }

    output = {
        "users": [],
        "conversations": [],
        "messages": defaultdict(lambda: defaultdict(list))  # {conv_id: {date: [messages]}}
    }

    with ZipFile(zip_uploaded_file, 'r') as zip_object:
        files = [f for f in zip_object.namelist() if '__MACOSX' not in f]

        channels = safe_json_read(zip_object, next((f for f in files if f.endswith("channels.json")), None))
        groups = safe_json_read(zip_object, next((f for f in files if f.endswith("groups.json")), None)) if any(f.endswith("groups.json") for f in files) else []
        dms = safe_json_read(zip_object, next((f for f in files if f.endswith("dms.json")), None)) if any(f.endswith("dms.json") for f in files) else []
        mpims = safe_json_read(zip_object, next((f for f in files if f.endswith("mpims.json")), None)) if any(f.endswith("mpims.json") for f in files) else []
        users_json = safe_json_read(zip_object, next((f for f in files if f.endswith("users.json")), None))

    # USERS - include all metadata
    for u in users_json:
        emp_data = employee_hashes.get(u["id"])
        if emp_data and u["id"] not in list_of_bots_ids:
            output["users"].append(emp_data)

    # CONVERSATIONS
    dm_counter = 1
    channel_counter = 1
    conv_meta_list = dms + mpims + channels + groups
    conv_id_map = {}  # Map original names to clarity IDs

    def generate_conversation_id(conv_original_id, is_dm):
        """Generate anonymized conversation ID using SHA-256 hashing"""
        hash_object = hashlib.sha256(conv_original_id.encode())
        hash_hex = hash_object.hexdigest()
        # Take first 10 chars and prepend 'D' for DM or 'C' for channel
        prefix = "D" if is_dm else "C"
        return prefix + hash_hex[:10].upper()

    for conv in conv_meta_list:
        members = [
            employee_hashes.get(m, {}).get("Clarity_ID")
            for m in conv.get("members", [])
            if employee_hashes.get(m) and m not in list_of_bots_ids
        ]

        if not members:
            continue

        is_dm = len(members) <= 3 or conv.get("is_im") or conv.get("is_mpim")
        
        # Use original conversation ID or name for hashing
        original_conv_id = conv.get("id", conv.get("name", ""))
        conv_id = generate_conversation_id(original_conv_id, is_dm)
        conv_type = "dm" if is_dm else "channel"

        conv_name = conv.get("name", conv.get("id", ""))
        conv_id_map[conv_name] = conv_id

        # Build conversation metadata
        conv_data = {
            "ConversationID": conv_id,
            "Type": conv_type,
            "Participants": ",".join(members),
            "MemberCount": len(members),
        }
        
        # Add created timestamp if present
        if conv.get("created"):
            conv_data["Created"] = conv.get("created")
        
        # Add creator (anonymized) if present
        if conv.get("creator"):
            creator_clarity = employee_hashes.get(conv.get("creator"), {}).get("Clarity_ID")
            if creator_clarity:
                conv_data["Creator"] = creator_clarity
        
        # Add archive status
        if conv.get("is_archived") is not None:
            conv_data["IsArchived"] = conv.get("is_archived")
        
        
        output["conversations"].append(conv_data)

    # MESSAGES - organized by conversation and date
    with ZipFile(zip_uploaded_file, 'r') as zip_object:
        folders = [f for f in zip_object.namelist() if f.endswith("/") and '__MACOSX' not in f]
        
        # Find all message files
        message_files = [f for f in zip_object.namelist() if f.endswith(".json") and '__MACOSX' not in f 
                        and not f.endswith("users.json") and not f.endswith("channels.json") 
                        and not f.endswith("groups.json") and not f.endswith("dms.json") and not f.endswith("mpims.json")]
        
        if not message_files:
            raise ValueError("No message files found in Slack export. Please ensure your export includes message history data.")

        for folder in folders:
            folder_name = folder.strip("/").split("/")[-1]
            conv_id = conv_id_map.get(folder_name)

            if not conv_id:
                continue

            for file in zip_object.namelist():
                if file.startswith(folder) and file.endswith(".json") and '__MACOSX' not in file:
                    try:
                        # Extract date from filename
                        date = os.path.basename(file).replace('.json', '')
                        
                        try:
                            msgs = safe_json_read(zip_object, file)
                        except Exception:
                            # Skip malformed files without exposing paths
                            continue
                        
                        if not msgs or not isinstance(msgs, list):
                            continue
                            
                        for msg in msgs:
                            if not isinstance(msg, dict):
                                continue

                            user_id = msg.get("user")
                            if not user_id or user_id in list_of_bots_ids + ['USLACKBOT']:
                                continue

                            clarity = employee_hashes.get(user_id, {}).get("Clarity_ID")
                            if not clarity:
                                continue

                            # Create anonymized message in Slack format with rounded timestamps
                            anonymized_msg = {
                                'user': clarity,
                                'ts': round_timestamp(msg.get('ts', '0'))
                            }
                            
                            # Add edited metadata if present
                            if msg.get('edited'):
                                edited_info = {}
                                if msg['edited'].get('ts'):
                                    edited_info['ts'] = round_timestamp(msg['edited'].get('ts'))
                                if msg['edited'].get('user'):
                                    editor_clarity = employee_hashes.get(msg['edited'].get('user'), {}).get('Clarity_ID')
                                    if editor_clarity:
                                        edited_info['user'] = editor_clarity
                                if edited_info:
                                    anonymized_msg['edited'] = edited_info

                            # Add thread_ts if present (rounded)
                            if msg.get('thread_ts'):
                                anonymized_msg['thread_ts'] = round_timestamp(msg.get('thread_ts'))
                            
                            # Add latest_reply if present (rounded)
                            if msg.get('latest_reply'):
                                anonymized_msg['latest_reply'] = round_timestamp(msg.get('latest_reply'))
                            
                            # Add reply_count if present
                            if msg.get('reply_count'):
                                anonymized_msg['reply_count'] = msg.get('reply_count')
                            
                            # Add reply_users_count if present
                            if msg.get('reply_users_count'):
                                anonymized_msg['reply_users_count'] = msg.get('reply_users_count')
                            
                            # Add reply_users if present (anonymize user IDs)
                            if msg.get('reply_users'):
                                anonymized_reply_users = []
                                for reply_user_id in msg.get('reply_users', []):
                                    if reply_user_id not in list_of_bots_ids:
                                        clarity_user = employee_hashes.get(reply_user_id, {}).get('Clarity_ID')
                                        if clarity_user:
                                            anonymized_reply_users.append(clarity_user)
                                if anonymized_reply_users:
                                    anonymized_msg['reply_users'] = anonymized_reply_users
                            
                            # Add replies metadata if present (anonymize user IDs)
                            if msg.get('replies'):
                                anonymized_replies = []
                                for reply in msg.get('replies', []):
                                    reply_user = reply.get('user')
                                    if reply_user and reply_user not in list_of_bots_ids:
                                        clarity_user = employee_hashes.get(reply_user, {}).get('Clarity_ID')
                                        if clarity_user:
                                            anonymized_replies.append({
                                                'user': clarity_user,
                                                'ts': round_timestamp(reply.get('ts', '0'))
                                            })
                                if anonymized_replies:
                                    anonymized_msg['replies'] = anonymized_replies

                            # Add reactions if present (with anonymized users, no reaction types)
                            if msg.get('reactions'):
                                anonymized_reactions = []
                                for reaction in msg.get('reactions', []):
                                    anonymized_users = [
                                        employee_hashes.get(u, {}).get('Clarity_ID')
                                        for u in reaction.get('users', [])
                                        if u not in list_of_bots_ids and employee_hashes.get(u)
                                    ]
                                    if anonymized_users:
                                        anonymized_reactions.append({
                                            'count': len(anonymized_users),
                                            'users': anonymized_users
                                        })
                                if anonymized_reactions:
                                    anonymized_msg['reactions'] = anonymized_reactions
                            
                            # Add last_read if present
                            if msg.get('last_read'):
                                anonymized_msg['last_read'] = msg.get('last_read')

                            output["messages"][conv_id][date].append(anonymized_msg)

                    except Exception:
                        # Skip problematic files silently - don't expose internal details
                        continue
    
    # Validate that we have some messages
    total_messages = sum(sum(len(msgs) for msgs in dates.values()) for dates in output.get('messages', {}).values())
    if total_messages == 0:
        raise ValueError("No messages were found or processed. Please ensure:\n"
                        "  1. Your Slack export contains message files\n"
                        "  2. Users in messages match users in your HRIS CSV\n"
                        "  3. The export includes actual conversation data (not just user/channel lists)")

    return output


def scrub_secrets(data):
    """Remove sensitive fields from preview data"""
    if isinstance(data, dict):
        return {k: scrub_secrets(v) for k, v in data.items() if k not in ['token', 'api_key', 'secret', 'password']}
    elif isinstance(data, list):
        return [scrub_secrets(item) for item in data]
    else:
        return data


def main():
    st.set_page_config(page_title="PII Sanitizer for CSV (Microsoft Presidio powered)", layout="wide")
    
    st.title("PII Sanitizer for CSV (Microsoft Presidio powered)")
    st.markdown("**Privacy-first Slack data anonymization** — No text content, no PII, just metadata")
    
    st.divider()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Upload HR CSV")
        uploaded_file = st.file_uploader("Employee data with email, role, team", type=["csv"], key="csv")
        if not uploaded_file:
            st.info("Upload a CSV file containing employee information")
            return
    
    with col2:
        st.subheader("Upload Slack Export ZIP")
        zip_uploaded_file = st.file_uploader("Original Slack workspace export", type=["zip"], key="zip")
        if not zip_uploaded_file:
            st.info("Upload your Slack export ZIP file")
            return

    st.divider()
    
    st.info("K-anonymity (k=5) automatically applied to: Role, Team, Work_Location, Employment_Status, Employment_Type, and Tenure_Band")
    
    st.divider()
    
    try:
        df, bot_ids = combine_data(uploaded_file, zip_uploaded_file)
        
        # Show data preview
        st.success(f"Data loaded: {len(df)} employees, {len(bot_ids)} bots detected")
        
        with st.expander("Preview Employee Data (k-anonymity applied)"):
            # Show only available columns
            available_cols = ['slack_id', 'Clarity_ID']
            for col in ['Role', 'Team', 'Work_Location', 'Employment_Status', 'Employment_Type', 'Tenure_Band']:
                if col in df.columns:
                    available_cols.append(col)
            preview_df = df[available_cols].head(10)
            st.dataframe(preview_df, use_container_width=True)
            st.caption(f"Showing first 10 of {len(df)} employees. K-anonymity applied to all filters (values with <5 occurrences → 'Others')")
        
    except ValueError as e:
        st.error(f"{str(e)}")
        return
    except Exception as e:
        st.error("An error occurred while processing your files. Please verify both files are valid and try again.")
        return

    st.divider()
    
    if st.button("Anonymize Slack Data", type="primary", use_container_width=True):
        try:
            with st.spinner("Scrubbing your secrets..."):
                output_data = extract_zip_files(zip_uploaded_file, df, bot_ids)

            message_count = sum(
                sum(len(msgs) for msgs in dates.values())
                for dates in output_data.get('messages', {}).values()
            )
        except ValueError as e:
            st.error(f"{str(e)}")
            return
        except Exception:
            st.error("An error occurred during anonymization. Please ensure your Slack export is complete and valid.")
            return
        
        # Display summary
        st.success("Anonymization complete!")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Users", len(output_data["users"]))
        with col2:
            st.metric("Conversations", len(output_data["conversations"]))
        with col3:
            st.metric("Messages", message_count)
        
        # Preview tabs
        tab1, tab2, tab3 = st.tabs(["Users Preview", "Conversations Preview", "Messages Preview"])
        
        with tab1:
            st.json(scrub_secrets(output_data["users"][:3]))
            st.caption(f"Showing 3 of {len(output_data['users'])} users")
        
        with tab2:
            st.json(scrub_secrets(output_data["conversations"][:3]))
            st.caption(f"Showing 3 of {len(output_data['conversations'])} conversations")
        
        with tab3:
            # Get first conversation with messages
            sample_messages = []
            for conv_id, dates in output_data.get('messages', {}).items():
                for date, messages in dates.items():
                    if messages:
                        sample_messages = messages[:3]
                        st.write(f"**Sample from:** `{conv_id}` on `{date}`")
                        break
                if sample_messages:
                    break
            
            if sample_messages:
                st.json(scrub_secrets(sample_messages))
                st.caption("Showing 3 sample messages (no text content included)")
            else:
                st.info("No messages found")
        
        st.divider()

        # Build ZIP with organized structure
        try:
            from io import BytesIO
            zip_buffer = BytesIO()
            with ZipFile(zip_buffer, "w") as zipf:
                zipf.writestr("users.json", json.dumps(output_data["users"], indent=2))
                zipf.writestr("conversations.json", json.dumps(output_data["conversations"], indent=2))
                
                # Write messages organized by conversation and date
                for conv_id, dates in output_data.get('messages', {}).items():
                    for date, messages in dates.items():
                        if messages:
                            file_path = f"messages/{conv_id}/{date}.json"
                            zipf.writestr(file_path, json.dumps(messages, indent=2))

            zip_buffer.seek(0)
            st.download_button(
                "Download Anonymized Slack Export",
                zip_buffer.getvalue(),
                "anonymized_slack_export.zip",
                "application/zip",
                type="primary",
                use_container_width=True
            )
        except Exception:
            st.error("Unable to create download file. Please try again.")
            return


if __name__ == "__main__":
    main()
