import streamlit as st
import pandas as pd
import json
import gc
from zipfile import ZipFile
from io import BytesIO

from utils.hashing import generate_salt, salted_hash
from utils.file_helpers import detect_delimiter, calculate_tenure_band
from utils.platform_detection import detect_platform, validate_export_structure
from parsers.slack_parser import parse_slack_export
from parsers.teams_parser import parse_teams_export
from datetime import datetime


def combine_data(uploaded_file, zip_uploaded_file, platform="slack"):
    """
    Combine HRIS data with Slack/Teams export data.
    
    Args:
        uploaded_file: HRIS CSV file
        zip_uploaded_file: Slack/Teams export ZIP
        platform: "slack" or "teams"
        
    Returns:
        tuple: (DataFrame with combined data, list of bot IDs)
    """
    # Read HRIS CSV
    delimiter = detect_delimiter(uploaded_file)
    uploaded_file.seek(0)
    hris_df = pd.read_csv(uploaded_file, delimiter=delimiter)
    
    # Normalize column names
    hris_df.columns = hris_df.columns.str.strip()
    
    # Detect email column
    email_col = None
    for col in hris_df.columns:
        if 'email' in col.lower() or 'e-mail' in col.lower():
            email_col = col
            break
    
    if not email_col:
        raise ValueError("Could not find email column in HRIS CSV. Please ensure there's an 'Email' column.")
    
    # Normalize emails and remove rows with missing emails
    hris_df[email_col] = hris_df[email_col].astype(str).str.lower().str.strip()
    hris_df = hris_df[hris_df[email_col].notna() & (hris_df[email_col] != '') & (hris_df[email_col] != 'nan')]
    
    # Calculate Tenure_Band from Date_of_Hire
    hris_df = calculate_tenure_band(hris_df)
    
    if platform == "slack":
        return _combine_slack_data(hris_df, email_col, zip_uploaded_file)
    else:  # teams
        return _combine_teams_data(hris_df, email_col, zip_uploaded_file)


def _combine_slack_data(hris_df, email_col, zip_uploaded_file):
    """Combine HRIS with Slack export."""
    from utils.file_helpers import safe_json_read
    from utils.platform_detection import get_file_from_zip
    
    with ZipFile(zip_uploaded_file, 'r') as zip_ref:
        # Read users.json
        users_file = get_file_from_zip(zip_ref, 'users.json')
        if not users_file:
            raise ValueError("Could not find 'users.json' in Slack export. Please ensure you've uploaded a complete export.")
        
        users_data = safe_json_read(zip_ref, users_file)
    
    # Identify bots
    bot_ids = [u['id'] for u in users_data if u.get('is_bot') or u.get('name') == 'slackbot']
    
    # Create Slack user lookup
    slack_users = []
    for user in users_data:
        if user.get('is_bot') or user.get('name') == 'slackbot':
            continue
        
        email = user.get('profile', {}).get('email', '').lower().strip()
        if email:
            slack_users.append({
                'email_address': email,
                'slack_id': user['id'],
                'timezone': user.get('tz')
            })
    
    slack_df = pd.DataFrame(slack_users)
    
    # Merge with HRIS
    employee_data = hris_df.merge(
        slack_df,
        left_on=email_col,
        right_on='email_address',
        how='outer',
        indicator=True
    )
    
    # Handle unmapped users
    slack_only_users = employee_data[employee_data[email_col].isna()].copy()
    if len(slack_only_users) > 0:
        unmapped_emails = slack_only_users['email_address'].dropna().tolist()
        st.warning(f"Found {len(unmapped_emails)} Slack user(s) not in HRIS: {', '.join(unmapped_emails[:3])}...")
    
    hris_only_users = employee_data[employee_data['slack_id'].isna()].copy()
    if len(hris_only_users) > 0:
        st.warning(f"{len(hris_only_users)} HRIS employee(s) not found in Slack export.")
    
    # Keep only matched users
    employee_data = employee_data[
        employee_data['slack_id'].notna() & employee_data[email_col].notna()
    ].copy()
    
    if len(employee_data) == 0:
        raise ValueError("No users could be matched between Slack export and HRIS data.")
    
    return employee_data, bot_ids


def _combine_teams_data(hris_df, email_col, zip_uploaded_file):
    """Combine HRIS with Teams export."""
    import csv
    from io import StringIO
    
    with ZipFile(zip_uploaded_file, 'r') as zip_ref:
        file_list = zip_ref.namelist()
        
        # Find Users.csv
        users_csv = next((f for f in file_list if f.endswith('Users.csv')), None)
        if not users_csv:
            raise ValueError("Could not find Users.csv in Teams export")
        
        users_content = zip_ref.read(users_csv).decode('utf-8')
        users_reader = csv.DictReader(StringIO(users_content))
        
        teams_users = []
        for user in users_reader:
            email = user.get('Email', '').lower().strip()
            if email:
                teams_users.append({
                    'email_address': email,
                    'teams_id': user.get('UserId', ''),
                    'display_name': user.get('DisplayName', '')
                })
    
    teams_df = pd.DataFrame(teams_users)
    
    # Merge with HRIS
    employee_data = hris_df.merge(
        teams_df,
        left_on=email_col,
        right_on='email_address',
        how='outer',
        indicator=True
    )
    
    # Handle unmapped users
    teams_only_users = employee_data[employee_data[email_col].isna()].copy()
    if len(teams_only_users) > 0:
        unmapped_emails = teams_only_users['email_address'].dropna().tolist()
        st.warning(f"Found {len(unmapped_emails)} Teams user(s) not in HRIS: {', '.join(unmapped_emails[:3])}...")
    
    hris_only_users = employee_data[employee_data['teams_id'].isna()].copy()
    if len(hris_only_users) > 0:
        st.warning(f"{len(hris_only_users)} HRIS employee(s) not found in Teams export.")
    
    # Keep only matched users
    employee_data = employee_data[
        employee_data['teams_id'].notna() & employee_data[email_col].notna()
    ].copy()
    
    if len(employee_data) == 0:
        raise ValueError("No users could be matched between Teams export and HRIS data.")
    
    # Bot detection (service accounts, etc.) - can be enhanced
    bot_ids = []
    
    return employee_data, bot_ids


def scrub_secrets(data):
    """Remove any remaining sensitive data from preview."""
    if isinstance(data, dict):
        return {k: scrub_secrets(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [scrub_secrets(item) for item in data]
    elif isinstance(data, str) and '@' in data:
        return "<EMAIL_REDACTED>"
    return data


def main():
    st.set_page_config(page_title="Clarity - Communication Data Anonymizer", layout="wide")
    
    # Initialize session state
    if 'session_id' not in st.session_state:
        import uuid
        st.session_state.session_id = str(uuid.uuid4())
    
    if 'uploaded_csv_name' not in st.session_state:
        st.session_state.uploaded_csv_name = None
    if 'uploaded_zip_name' not in st.session_state:
        st.session_state.uploaded_zip_name = None
    if 'platform' not in st.session_state:
        st.session_state.platform = 'Slack'
    
    st.title("Clarity")
    st.markdown("**Privacy-first communication data anonymization** — No text content, no PII, just metadata")
    
    st.divider()
    
    # Platform selection
    platform = st.radio(
        "Select Platform",
        ["Slack", "Microsoft Teams"],
        horizontal=True,
        help="Choose the platform your export is from"
    )
    
    # Reset data if platform changes
    if st.session_state.platform != platform:
        st.session_state.platform = platform
        if 'processed_data' in st.session_state:
            del st.session_state.processed_data
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Upload HR CSV")
        uploaded_file = st.file_uploader("Employee data with email, role, team", type=["csv"], key="csv")
        
        if uploaded_file:
            if st.session_state.uploaded_csv_name != uploaded_file.name:
                st.session_state.uploaded_csv_name = uploaded_file.name
                if 'processed_data' in st.session_state:
                    del st.session_state.processed_data
        
        if not uploaded_file:
            st.info("Upload a CSV file containing employee information")
            return
    
    with col2:
        platform_name = "Slack" if platform == "Slack" else "Microsoft Teams"
        st.subheader(f"Upload {platform_name} Export ZIP")
        
        help_text = {
            "Slack": "Upload your Slack workspace export ZIP file",
            "Microsoft Teams": "Upload your Teams export ZIP file (from Teams Admin Center or eDiscovery)"
        }
        
        zip_uploaded_file = st.file_uploader(
            f"Original {platform_name} export",
            type=["zip"],
            key="zip",
            help=help_text[platform]
        )
        
        if zip_uploaded_file:
            if st.session_state.uploaded_zip_name != zip_uploaded_file.name:
                st.session_state.uploaded_zip_name = zip_uploaded_file.name
                if 'processed_data' in st.session_state:
                    del st.session_state.processed_data
        
        if not zip_uploaded_file:
            st.info(f"Upload your {platform_name} export ZIP file")
            return

    st.divider()
    
    # Auto-detect and validate platform
    detected_platform = None
    try:
        detected_platform = detect_platform(zip_uploaded_file)
        validation = validate_export_structure(zip_uploaded_file, detected_platform)
        
        if validation['warnings']:
            for warning in validation['warnings']:
                st.warning(warning)
        
        # Check if detected platform matches selection
        if detected_platform != platform.lower().replace("microsoft ", ""):
            st.warning(
                f"Detected {detected_platform.upper()} export, but you selected {platform}. "
                f"Using detected platform: {detected_platform.upper()}"
            )
            platform = "Slack" if detected_platform == "slack" else "Microsoft Teams"
        else:
            st.success(f"✓ Detected {detected_platform.upper()} export ({validation['file_count']} files)")
    
    except ValueError as e:
        st.error(f"Export validation failed: {str(e)}")
        return
    except Exception as e:
        st.warning(f"Could not auto-detect platform: {str(e)}. Using selected platform: {platform}")
        detected_platform = platform.lower().replace("microsoft ", "")
    
    # Generate salt
    if 'session_salt' not in st.session_state:
        st.session_state.session_salt = generate_salt()
    
    # Process data
    try:
        if 'processed_data' not in st.session_state or st.session_state.get('force_reprocess'):
            df, bot_ids = combine_data(uploaded_file, zip_uploaded_file, detected_platform)
            
            st.session_state.processed_data = {
                'df': df, 
                'bot_ids': bot_ids,
                'platform': detected_platform
            }
            st.session_state.force_reprocess = False
        else:
            df = st.session_state.processed_data['df']
            bot_ids = st.session_state.processed_data['bot_ids']
            detected_platform = st.session_state.processed_data.get('platform', detected_platform)
        
        st.success(f"Data loaded: {len(df)} employees, {len(bot_ids)} bots detected")
        
        with st.expander("Preview Employee Data"):
            id_col = 'slack_id' if detected_platform == "slack" else 'teams_id'
            available_cols = [id_col]
            for col in ['Role', 'Team', 'Work_Location', 'Employment_Status', 'Employment_Type', 'Tenure_Band']:
                if col in df.columns:
                    available_cols.append(col)
            preview_df = df[available_cols].head(10)
            st.dataframe(preview_df, use_container_width=True)
            st.caption(f"Showing first 10 of {len(df)} employees.")
        
    except ValueError as e:
        st.error(f"{str(e)}")
        return
    except Exception as e:
        st.error(f"An error occurred while processing your files: {str(e)}")
        return

    st.divider()
    
    button_label = f"Anonymize {platform} Data"
    if st.button(button_label, type="primary", use_container_width=True):
        try:
            with st.spinner("Anonymizing data..."):
                if detected_platform == "slack":
                    output_data = parse_slack_export(
                        zip_uploaded_file, 
                        df, 
                        bot_ids, 
                        st.session_state.session_salt
                    )
                else:  # Microsoft Teams
                    output_data = parse_teams_export(
                        zip_uploaded_file, 
                        df, 
                        bot_ids, 
                        st.session_state.session_salt
                    )

            message_count = sum(
                sum(len(msgs) for msgs in dates.values())
                for dates in output_data.get('messages', {}).values()
            )
        except ValueError as e:
            st.error(f"{str(e)}")
            return
        except Exception as e:
            st.error(f"An error occurred during anonymization: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
            return
        
        st.success("Anonymization complete!")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Users", len(output_data.get("users", [])))
        with col2:
            st.metric("Conversations", len(output_data.get("conversations", [])))
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

        # Build download package
        try:
            zip_buffer = BytesIO()
            with ZipFile(zip_buffer, "w") as zipf:
                zipf.writestr("users.json", json.dumps(output_data["users"], indent=2))
                zipf.writestr("conversations.json", json.dumps(output_data["conversations"], indent=2))
                
                # Export messages in Slack folder structure: messages/conv_id/date.json
                for conv_id, dates in output_data.get('messages', {}).items():
                    for date, messages in dates.items():
                        if messages:
                            file_path = f"messages/{conv_id}/{date}.json"
                            zipf.writestr(file_path, json.dumps(messages, indent=2))

            zip_buffer.seek(0)
            
            # Prepare filter mappings
            mappings_json = json.dumps(output_data.get("filter_mappings", {}), indent=2)
            mappings_bytes = mappings_json.encode('utf-8')
            
            # Create combined ZIP
            combined_zip_buffer = BytesIO()
            with ZipFile(combined_zip_buffer, "w") as combined_zipf:
                platform_prefix = detected_platform
                combined_zipf.writestr(f"anonymized_{platform_prefix}_export.zip", zip_buffer.getvalue())
                combined_zipf.writestr("filter_mappings.json", mappings_bytes)
            
            combined_zip_buffer.seek(0)
            
            st.download_button(
                "Download Anonymized Data & Filter Mappings",
                combined_zip_buffer.getvalue(),
                "clarity_export.zip",
                "application/zip",
                type="primary",
                use_container_width=True,
                on_click=lambda: cleanup_session()
            )
                                                 
        except Exception as e:
            st.error(f"Unable to create download file: {str(e)}")
            return


def cleanup_session():
    """Clear all sensitive session data from memory and destroy salt."""
    keys_to_clear = [
        'session_salt',
        'processed_data',
        'uploaded_csv_name',
        'uploaded_zip_name',
        'force_reprocess'
    ]
    
    # Explicitly delete data from session state
    for key in keys_to_clear:
        if key in st.session_state:
            # Overwrite salt with zeros before deletion
            if key == 'session_salt' and st.session_state[key]:
                st.session_state[key] = None
            # Clear dataframe from memory
            elif key == 'processed_data' and isinstance(st.session_state.get(key), dict):
                if 'df' in st.session_state[key]:
                    st.session_state[key]['df'] = None
                st.session_state[key] = None
            
            del st.session_state[key]
    
    # Force garbage collection to clear memory
    gc.collect()


if __name__ == "__main__":
    main()
