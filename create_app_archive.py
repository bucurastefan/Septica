#!/usr/bin/env python3
import zipfile
import os
import sys

def create_app_archive():
    """Create a zip archive with the Flask application files"""
    
    # Define the files and folders to include
    files_to_include = [
        'flask_auth_app/app.py',
        'flask_auth_app/Procfile', 
        'flask_auth_app/requirements.txt',
        'flask_auth_app/users.db',
        'flask_auth_app/game_logic.py'
    ]
    
    folders_to_include = [
        'flask_auth_app/templates',
        'flask_auth_app/static'
    ]
    
    # Create the zip file
    zip_filename = 'app.zip'
    
    try:
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            print(f"Creating {zip_filename}...")
            
            # Add individual files
            for file_path in files_to_include:
                if os.path.exists(file_path):
                    # Store with relative path inside the zip (remove flask_auth_app prefix)
                    archive_name = file_path.replace('flask_auth_app/', '')
                    zipf.write(file_path, archive_name)
                    print(f"  Added: {archive_name}")
                else:
                    print(f"  Warning: {file_path} not found, skipping...")
            
            # Add folders recursively
            for folder_path in folders_to_include:
                if os.path.exists(folder_path):
                    for root, dirs, files in os.walk(folder_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            # Store with relative path inside the zip (remove flask_auth_app prefix)
                            archive_name = file_path.replace('flask_auth_app/', '')
                            zipf.write(file_path, archive_name)
                            print(f"  Added: {archive_name}")
                else:
                    print(f"  Warning: {folder_path} not found, skipping...")
        
        print(f"\n✅ Successfully created {zip_filename}")
        
        # Show archive contents
        print(f"\n📁 Archive contents:")
        with zipfile.ZipFile(zip_filename, 'r') as zipf:
            for name in sorted(zipf.namelist()):
                print(f"  {name}")
        
        # Show file size
        size_mb = os.path.getsize(zip_filename) / (1024 * 1024)
        print(f"\n📊 Archive size: {size_mb:.2f} MB")
        
    except Exception as e:
        print(f"❌ Error creating archive: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_app_archive()
