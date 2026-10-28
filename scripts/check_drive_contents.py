import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "backend"))

from app.services.google_drive_storage import get_google_drive_service
from googleapiclient.discovery import build

svc = get_google_drive_service()
creds = svc.get_credentials()
drive = build("drive", "v3", credentials=creds)

root_id = "1HSmEYSlw57hQkW4FBLft_-11e6sR72Qk"

# 1. Check root folders
q = f"'{root_id}' in parents and trashed = false"
res = drive.files().list(q=q, fields="files(id, name, mimeType)").execute()
folders = res.get("files", [])
print("Folders inside OM-Search-Data:")
for f in folders:
    print(f" - {f['name']} (ID: {f['id']}, Type: {f['mimeType']})")

# 2. Check files inside page-records folder
page_records_id = None
for f in folders:
    if f["name"] == "page-records":
        page_records_id = f["id"]
        break

if page_records_id:
    q_pages = f"'{page_records_id}' in parents and trashed = false"
    res_pages = drive.files().list(q=q_pages, pageSize=10, fields="nextPageToken, files(id, name, size, createdTime)").execute()
    sample_files = res_pages.get("files", [])
    print(f"\nSample files in 'page-records' (Folder ID: {page_records_id}):")
    for sf in sample_files[:5]:
        print(f" - {sf.get('name')} | Size: {sf.get('size')} bytes | Created: {sf.get('createdTime')}")
        
    # Count total files in page-records
    count = 0
    total_size = 0
    page_token = None
    while True:
        resp = drive.files().list(q=q_pages, pageSize=1000, fields="nextPageToken, files(id, size)", pageToken=page_token).execute()
        flist = resp.get("files", [])
        count += len(flist)
        for fl in flist:
            total_size += int(fl.get("size", 0))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
            
    print(f"\nTotal files in Google Drive 'page-records': {count} files")
    print(f"Total size in Google Drive 'page-records': {total_size / (1024*1024):.2f} MB ({total_size / (1024*1024*1024):.3f} GB)")

# 3. Check Google Drive Quota
about = drive.about().get(fields="storageQuota, user").execute()
print("\nGoogle Drive Quota:")
print(f"User: {about.get('user', {}).get('emailAddress')}")
sq = about.get("storageQuota", {})
print(f"Limit: {int(sq.get('limit', 0)) / (1024**4):.2f} TB")
print(f"Usage: {int(sq.get('usage', 0)) / (1024**3):.2f} GB")
print(f"Usage in Drive: {int(sq.get('usageInDrive', 0)) / (1024**3):.2f} GB")
