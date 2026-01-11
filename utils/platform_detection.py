"""Platform detection and export validation."""
from zipfile import ZipFile
import streamlit as st


def detect_platform(zip_file):
    """
    Auto-detect platform from export ZIP structure.
    
    Args:
        zip_file: Uploaded ZIP file
        
    Returns:
        str: "slack" or "teams"
        
    Raises:
        ValueError: If platform cannot be detected
    """
    with ZipFile(zip_file, 'r') as zip_ref:
        file_list = zip_ref.namelist()
        file_list_lower = [f.lower() for f in file_list]
        
        # Slack indicators (handle nested folders and __MACOSX)
        has_slack_users = any('users.json' in f for f in file_list_lower)
        has_slack_channels = any('channels.json' in f for f in file_list_lower)
        has_slack_integration_logs = any('integration_logs.json' in f for f in file_list_lower)
        has_slack_canvases = any('canvases.json' in f for f in file_list_lower)
   
        # Teams indicators
        has_teams_users = any('users.csv' in f for f in file_list_lower)
        has_teams_summary = any('exportsummary.csv' in f for f in file_list_lower)
        has_teams_manifest = any('manifest.xml' in f for f in file_list_lower)
        
        if has_slack_users or has_slack_channels or has_slack_integration_logs or has_slack_canvases:
            return "slack"
        elif has_teams_users or has_teams_summary or has_teams_manifest:
            return "teams"
        else:
            # Show what we found to help debug
            raise ValueError(
                f"Could not detect platform from export structure.\n\n"
                f"Files found: {', '.join(file_list[:10])}\n\n"
                f"Expected for Slack: users.json, channels.json\n"
                f"Expected for Teams: Users.csv, ExportSummary.csv\n\n"
                f"Please ensure you've uploaded a valid export file."
            )


def validate_export_structure(zip_file, platform):
    """
    Validate export structure for the given platform.
    
    Args:
        zip_file: Uploaded ZIP file
        platform: "slack" or "teams"
        
    Returns:
        dict: Validation results with warnings and file counts
        
    Raises:
        ValueError: If export is invalid
    """
    results = {
        'valid': True,
        'warnings': [],
        'file_count': 0,
        'root_folder': None
    }
    
    with ZipFile(zip_file, 'r') as zip_ref:
        file_list = zip_ref.namelist()
        file_list_lower = [f.lower() for f in file_list]
        
        # Filter out __MACOSX files
        clean_files = [f for f in file_list if not f.startswith('__MACOSX')]
        results['file_count'] = len(clean_files)
        
        # Detect root folder (common in Slack exports)
        folders = [f for f in clean_files if f.endswith('/')]
        if folders:
            # Get the most common root folder
            root_folder = folders[0] if folders else ''
            results['root_folder'] = root_folder
        
        if platform == "slack":
            # Check for required Slack files (handle nested structure)
            has_users = any('users.json' in f for f in file_list_lower)
            if not has_users:
                raise ValueError(
                    "Invalid Slack export: 'users.json' not found. "
                    "Please export from Slack Settings > Import/Export Data > Export."
                )
            
            has_channels = any('channels.json' in f for f in file_list_lower)
            if not has_channels:
                results['warnings'].append("No 'channels.json' found - only DMs will be processed")
            
            # Check for message files (JSON files in subdirectories)
            message_files = [f for f in clean_files if f.endswith('.json') and '/' in f and not f.endswith('users.json') and not f.endswith('channels.json')]
            if not message_files:
                results['warnings'].append("No message files found in export")
        
        elif platform == "teams":
            # Check for required Teams files (case-insensitive)
            users_csv = any('users.csv' in f for f in file_list_lower)
            if not users_csv:
                raise ValueError(
                    "Invalid Teams export: 'Users.csv' not found. "
                    "Please ensure you've exported from Teams Admin Center or eDiscovery."
                )
            
            summary_csv = any('exportsummary.csv' in f for f in file_list_lower)
            if not summary_csv:
                results['warnings'].append("No 'ExportSummary.csv' found - limited data will be available")
    
    return results


def get_file_from_zip(zip_ref, filename):
    """
    Get a file from ZIP, handling nested folders.
    
    Args:
        zip_ref: ZipFile object
        filename: File to find (e.g., 'users.json')
        
    Returns:
        str: Full path to file in ZIP, or None if not found
    """
    file_list = zip_ref.namelist()
    
    # Try exact match first
    if filename in file_list:
        return filename
    
    # Search in nested folders (case-insensitive)
    filename_lower = filename.lower()
    for f in file_list:
        if f.lower().endswith(filename_lower) and not f.startswith('__MACOSX'):
            return f
    
    return None