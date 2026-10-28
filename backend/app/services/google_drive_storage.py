import os
import json
import base64
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories.database import (
    get_db_manager,
    DriveOAuthCredential,
    DriveUploadBatch,
    DriveStorageReport,
)

logger = logging.getLogger(__name__)

# Google API client imports
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False
    logger.warning("Google API client libraries not available in current environment.")

# Cache PKCE code_verifiers indexed by oauth_state
_oauth_code_verifiers: Dict[str, str] = {}


class GoogleDriveStorageService:
    """
    Durable, cloud-first page archive storage service using Google Drive API.
    Designed for Google One 5 TB storage integration.
    """

    SUBFOLDERS = [
        "page-records",
        "archive-manifests",
        "index-exports",
        "ingestion-reports",
    ]

    def __init__(self):
        self.settings = get_settings()
        self._encryption_key = self._derive_encryption_key()

    def _derive_encryption_key(self) -> bytes:
        """Derive durable Fernet encryption key from operator secret or dedicated key."""
        raw_key = self.settings.GOOGLE_ENCRYPTION_KEY or self.settings.OPERATOR_API_KEY or "om-search-cloud-key-salt"
        salt = b"om_search_gdrive_vault_salt_v1"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        return base64.urlsafe_b64encode(kdf.derive(raw_key.encode("utf-8")))

    def _encrypt(self, plain_text: str) -> str:
        f = Fernet(self._encryption_key)
        return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")

    def _decrypt(self, cipher_text: str) -> str:
        f = Fernet(self._encryption_key)
        return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")

    def get_authorization_url(self, redirect_uri: Optional[str] = None, state: Optional[str] = None) -> Tuple[str, str]:
        """
        Build OAuth 2.0 authorization URL for connecting user's Google Drive.
        Enforces offline access and explicit consent to secure refresh_token.
        """
        if not self.settings.GOOGLE_CLIENT_ID or not self.settings.GOOGLE_CLIENT_SECRET:
            raise ValueError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be configured in environment or .env"
            )

        redirect = redirect_uri or self.settings.GOOGLE_REDIRECT_URI
        import secrets
        oauth_state = state or secrets.token_urlsafe(32)

        client_config = {
            "web": {
                "client_id": self.settings.GOOGLE_CLIENT_ID,
                "client_secret": self.settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect],
            }
        }

        flow = Flow.from_client_config(
            client_config,
            scopes=self.settings.GOOGLE_DRIVE_SCOPES,
            state=oauth_state,
        )
        flow.redirect_uri = redirect
        flow.autogenerate_code_verifier = False

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        if hasattr(flow, "code_verifier") and flow.code_verifier:
            _oauth_code_verifiers[oauth_state] = flow.code_verifier
        return auth_url, oauth_state

    def handle_oauth_callback(
        self,
        code: str,
        state: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens, encrypt and persist credentials,
        and automatically bootstrap the OM-Search-Data folder structure in Drive.
        """
        redirect = redirect_uri or self.settings.GOOGLE_REDIRECT_URI

        client_config = {
            "web": {
                "client_id": self.settings.GOOGLE_CLIENT_ID,
                "client_secret": self.settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect],
            }
        }

        flow = Flow.from_client_config(
            client_config,
            scopes=self.settings.GOOGLE_DRIVE_SCOPES,
        )
        flow.redirect_uri = redirect
        flow.autogenerate_code_verifier = False

        # Attach PKCE code_verifier if one was recorded
        if state and state in _oauth_code_verifiers:
            flow.code_verifier = _oauth_code_verifiers.pop(state)
        elif _oauth_code_verifiers:
            most_recent_key = list(_oauth_code_verifiers.keys())[-1]
            flow.code_verifier = _oauth_code_verifiers.pop(most_recent_key)

        flow.fetch_token(code=code)

        creds = flow.credentials
        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or []),
        }

        encrypted_tokens = self._encrypt(json.dumps(token_data))

        # Query user info and quota from Drive API
        drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
        about = drive_service.about().get(fields="storageQuota,user").execute()
        user_info = about.get("user", {})
        user_email = user_info.get("emailAddress", "unknown")
        storage_quota = about.get("storageQuota", {})
        quota_total = int(storage_quota.get("limit", 0)) if storage_quota.get("limit") else None
        quota_used = int(storage_quota.get("usage", 0)) if storage_quota.get("usage") else None

        # Bootstrap or locate root and subfolders
        root_folder_id = self.settings.GOOGLE_DRIVE_ROOT_FOLDER_ID
        if not root_folder_id:
            root_folder_id = self._get_or_create_folder(
                drive_service,
                self.settings.GOOGLE_DRIVE_ROOT_FOLDER_NAME,
            )

        subfolder_ids = {}
        for sub_name in self.SUBFOLDERS:
            sub_id = self._get_or_create_folder(
                drive_service,
                sub_name,
                parent_id=root_folder_id,
            )
            subfolder_ids[sub_name] = sub_id

        # Persist in DB
        should_close_db = False
        if db is None:
            db = get_db_manager().get_session()
            should_close_db = True

        try:
            # Deactivate previous credentials
            db.query(DriveOAuthCredential).update({"is_active": 0})

            cred_record = DriveOAuthCredential(
                user_email=user_email,
                encrypted_tokens=encrypted_tokens,
                root_folder_id=root_folder_id,
                subfolder_ids_json=json.dumps(subfolder_ids),
                is_active=1,
                storage_quota_total_bytes=quota_total,
                storage_quota_used_bytes=quota_used,
                connected_at=datetime.now(timezone.utc),
            )
            db.add(cred_record)
            db.commit()
            db.refresh(cred_record)

            logger.info("Successfully connected Google Drive account: %s", user_email)
            return {
                "status": "connected",
                "user_email": user_email,
                "root_folder_id": root_folder_id,
                "subfolders": subfolder_ids,
                "quota_total_bytes": quota_total,
                "quota_used_bytes": quota_used,
            }
        finally:
            if should_close_db:
                db.close()

    def get_credentials(self, db: Optional[Session] = None) -> Optional[Credentials]:
        """Retrieve and automatically refresh active Google OAuth credentials."""
        if not GOOGLE_LIBS_AVAILABLE:
            return None

        should_close = False
        if db is None:
            db = get_db_manager().get_session()
            should_close = True

        try:
            cred_row = (
                db.query(DriveOAuthCredential)
                .filter(DriveOAuthCredential.is_active == 1)
                .order_by(DriveOAuthCredential.id.desc())
                .first()
            )
            if not cred_row:
                # Cloud runner / CI / GitHub Actions fallback from environment
                # 1. Check for JSON credential blob first
                json_cred_str = (
                    os.environ.get("GOOGLE_CREDENTIALS")
                    or os.environ.get("GDRIVE_CREDENTIALS")
                    or os.environ.get("CREDENTIALS_JSON")
                    or os.environ.get("GDRIVE_SECRET")
                )
                refresh_token = None
                client_id = None
                client_secret = None

                if json_cred_str:
                    try:
                        raw_json = json.loads(json_cred_str.strip())
                        # Could be installed/web OAuth json or token json
                        installed = raw_json.get("installed") or raw_json.get("web") or raw_json
                        client_id = installed.get("client_id")
                        client_secret = installed.get("client_secret")
                        refresh_token = installed.get("refresh_token") or raw_json.get("refresh_token")
                    except Exception as e:
                        logger.warning("Could not parse JSON credentials from environment: %s", e)

                # 2. Check all possible secret alias names
                refresh_token = (
                    refresh_token
                    or os.environ.get("GOOGLE_REFRESH_TOKEN")
                    or os.environ.get("GDRIVE_REFRESH_TOKEN")
                    or os.environ.get("REFRESH_TOKEN")
                    or os.environ.get("GOOGLE_DRIVE_REFRESH_TOKEN")
                    or os.environ.get("DRIVE_REFRESH_TOKEN")
                    or os.environ.get("GDRIVE_TOKEN")
                    or os.environ.get("DRIVE_TOKEN")
                )
                client_id = (
                    client_id
                    or os.environ.get("GOOGLE_CLIENT_ID")
                    or os.environ.get("GDRIVE_CLIENT_ID")
                    or os.environ.get("CLIENT_ID")
                    or os.environ.get("GOOGLE_DRIVE_CLIENT_ID")
                    or self.settings.GOOGLE_CLIENT_ID
                )
                client_secret = (
                    client_secret
                    or os.environ.get("GOOGLE_CLIENT_SECRET")
                    or os.environ.get("GDRIVE_CLIENT_SECRET")
                    or os.environ.get("CLIENT_SECRET")
                    or os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET")
                    or self.settings.GOOGLE_CLIENT_SECRET
                )

                if refresh_token and client_id and client_secret:
                    creds = Credentials(
                        token=None,
                        refresh_token=refresh_token.strip(),
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=client_id.strip(),
                        client_secret=client_secret.strip(),
                        scopes=self.settings.GOOGLE_DRIVE_SCOPES,
                    )
                    try:
                        creds.refresh(Request())
                        logger.info("Successfully authenticated Google Drive via environment secrets.")
                        return creds
                    except Exception as e:
                        logger.error("Failed to refresh Google Drive credentials from environment secrets: %s", e)
                        self._last_auth_error = f"Token refresh failed: {e}"
                        return None
                else:
                    missing = []
                    if not client_id:
                        missing.append("GOOGLE_CLIENT_ID")
                    if not client_secret:
                        missing.append("GOOGLE_CLIENT_SECRET")
                    if not refresh_token:
                        missing.append("GOOGLE_REFRESH_TOKEN")
                    self._last_auth_error = f"Missing required credentials: {', '.join(missing)}"
                    logger.warning("Google Drive credentials incomplete in environment. Missing: %s", missing)
                    return None

            token_data = json.loads(self._decrypt(cred_row.encrypted_tokens))
            creds = Credentials(
                token=token_data.get("token"),
                refresh_token=token_data.get("refresh_token"),
                token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=token_data.get("client_id", self.settings.GOOGLE_CLIENT_ID),
                client_secret=token_data.get("client_secret", self.settings.GOOGLE_CLIENT_SECRET),
                scopes=token_data.get("scopes", self.settings.GOOGLE_DRIVE_SCOPES),
            )

            # Auto refresh if expired or about to expire
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    # Update persisted token
                    token_data["token"] = creds.token
                    cred_row.encrypted_tokens = self._encrypt(json.dumps(token_data))
                    cred_row.updated_at = datetime.now(timezone.utc)
                    db.commit()
                except Exception as e:
                    logger.error("Failed to refresh Google Drive OAuth token: %s", e)
                    return None

            return creds
        finally:
            if should_close:
                db.close()

    def disconnect(self, db: Optional[Session] = None) -> bool:
        """Deactivate credentials and disconnect Google Drive integration."""
        should_close = False
        if db is None:
            db = get_db_manager().get_session()
            should_close = True

        try:
            db.query(DriveOAuthCredential).filter(DriveOAuthCredential.is_active == 1).update({"is_active": 0})
            db.commit()
            logger.info("Google Drive connection safely disconnected.")
            return True
        finally:
            if should_close:
                db.close()

    def get_status(self, db: Optional[Session] = None) -> Dict[str, Any]:
        """Inspect Google Drive storage connection, root folders, and 5 TB quota headroom."""
        should_close = False
        if db is None:
            db = get_db_manager().get_session()
            should_close = True

        try:
            creds = self.get_credentials(db=db)
            if not creds:
                err_msg = getattr(self, "_last_auth_error", None) or "No active Google Drive credentials found. Connect via /api/v1/storage/google-drive/connect"
                return {
                    "connected": False,
                    "reason": err_msg,
                    "storage_budget_bytes": self.settings.GOOGLE_DRIVE_STORAGE_BUDGET_BYTES,
                    "target_capacity": "5 TB (Google One)",
                }

            cred_row = (
                db.query(DriveOAuthCredential)
                .filter(DriveOAuthCredential.is_active == 1)
                .order_by(DriveOAuthCredential.id.desc())
                .first()
            )

            user_email = (cred_row.user_email if cred_row else None) or "omprasadbhaskar07@gmail.com"
            root_folder_id = (
                (cred_row.root_folder_id if cred_row else None)
                or os.environ.get("GOOGLE_DRIVE_ROOT_FOLDER_ID")
                or self.settings.GOOGLE_DRIVE_ROOT_FOLDER_ID
                or "1HSmEYSlw57hQkW4FBLft_-11e6sR72Qk"
            )

            # Fetch fresh quota usage
            subfolders = {}
            if cred_row and cred_row.subfolder_ids_json:
                try:
                    subfolders = json.loads(cred_row.subfolder_ids_json)
                except Exception:
                    pass

            quota_info = {
                "total_bytes": (cred_row.storage_quota_total_bytes if cred_row else None) or self.settings.GOOGLE_DRIVE_STORAGE_BUDGET_BYTES,
                "used_bytes": (cred_row.storage_quota_used_bytes if cred_row else None) or 0,
            }

            try:
                service = build("drive", "v3", credentials=creds, cache_discovery=False)
                about = service.about().get(fields="storageQuota,user").execute()
                u_info = about.get("user", {})
                if u_info.get("emailAddress"):
                    user_email = u_info["emailAddress"]
                sq = about.get("storageQuota", {})
                if sq.get("limit"):
                    quota_info["total_bytes"] = int(sq["limit"])
                    if cred_row:
                        cred_row.storage_quota_total_bytes = quota_info["total_bytes"]
                if sq.get("usage"):
                    quota_info["used_bytes"] = int(sq["usage"])
                    if cred_row:
                        cred_row.storage_quota_used_bytes = quota_info["used_bytes"]
                if cred_row:
                    db.commit()
            except Exception as e:
                logger.warning("Could not fetch real-time quota from Google Drive API: %s", e)

            used_pct = round((quota_info["used_bytes"] / max(1, quota_info["total_bytes"])) * 100, 2)

            # Query upload statistics from database
            total_batches = db.query(DriveUploadBatch).count()
            uploaded_batches = db.query(DriveUploadBatch).filter(DriveUploadBatch.upload_status == "verified").count()
            failed_batches = db.query(DriveUploadBatch).filter(DriveUploadBatch.upload_status == "failed").count()
            pending_batches = db.query(DriveUploadBatch).filter(DriveUploadBatch.upload_status.in_(["pending", "uploading"])).count()
            from sqlalchemy import func
            total_bytes_uploaded = db.query(func.sum(DriveUploadBatch.compressed_bytes)).filter(DriveUploadBatch.upload_status == "verified").scalar() or 0
            total_docs_uploaded = db.query(func.sum(DriveUploadBatch.record_count)).filter(DriveUploadBatch.upload_status == "verified").scalar() or 0

            return {
                "connected": True,
                "user_email": user_email,
                "root_folder_id": root_folder_id,
                "subfolders": subfolders,
                "quota": {
                    "total_bytes": quota_info["total_bytes"],
                    "used_bytes": quota_info["used_bytes"],
                    "available_bytes": max(0, quota_info["total_bytes"] - quota_info["used_bytes"]),
                    "used_percent": used_pct,
                    "plan": "Google One 5 TB",
                },
                "batch_statistics": {
                    "total_batches": total_batches,
                    "verified_uploaded": uploaded_batches,
                    "pending_uploads": pending_batches,
                    "failed_uploads": failed_batches,
                    "total_documents_archived": int(total_docs_uploaded),
                    "total_compressed_bytes_archived": int(total_bytes_uploaded),
                },
                "connected_at": cred_row.connected_at.isoformat() if (cred_row and cred_row.connected_at) else datetime.now(timezone.utc).isoformat(),
            }
        finally:
            if should_close:
                db.close()

    def _get_or_create_folder(
        self,
        service,
        folder_name: str,
        parent_id: Optional[str] = None,
    ) -> str:
        """Find existing folder or create it idempotently in Google Drive."""
        query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        res = service.files().list(q=query, fields="files(id, name)").execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]

        folder_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            folder_metadata["parents"] = [parent_id]

        folder = service.files().create(body=folder_metadata, fields="id").execute()
        return folder.get("id")

    def upload_batch(
        self,
        batch_id: str,
        local_filepath: str,
        subfolder_name: str = "page-records",
        mime_type: str = "application/gzip",
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Stream resumable upload of a compressed batch to Google Drive.
        Verifies uploaded file size, creates manifest, and returns durable file ID.
        """
        p = Path(local_filepath)
        if not p.exists():
            raise FileNotFoundError(f"Local spool file does not exist: {local_filepath}")

        expected_size = p.stat().st_size

        should_close = False
        if db is None:
            db = get_db_manager().get_session()
            should_close = True

        try:
            creds = self.get_credentials(db=db)
            if not creds:
                raise PermissionError("Google Drive is not connected or authorization is revoked.")

            service = build("drive", "v3", credentials=creds, cache_discovery=False)

            cred_row = (
                db.query(DriveOAuthCredential)
                .filter(DriveOAuthCredential.is_active == 1)
                .first()
            )
            subfolders = {}
            folder_id = None
            if cred_row:
                try:
                    subfolders = json.loads(cred_row.subfolder_ids_json or "{}")
                except Exception:
                    pass
                folder_id = subfolders.get(subfolder_name) or cred_row.root_folder_id

            if not folder_id:
                root_id = (
                    os.environ.get("GOOGLE_DRIVE_ROOT_FOLDER_ID")
                    or self.settings.GOOGLE_DRIVE_ROOT_FOLDER_ID
                    or "1HSmEYSlw57hQkW4FBLft_-11e6sR72Qk"
                )
                folder_id = self._get_or_create_folder(service, subfolder_name, parent_id=root_id)

            file_metadata = {
                "name": p.name,
                "parents": [folder_id],
                "description": f"OM Search durable page batch {batch_id}",
            }

            media = MediaFileUpload(
                str(p),
                mimetype=mime_type,
                resumable=True,
                chunksize=5 * 1024 * 1024,  # 5 MB upload chunks
            )

            request = service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, name, size, webViewLink, md5Checksum",
            )

            response = None
            while response is None:
                for attempt in range(1, 21):
                    try:
                        status, response = request.next_chunk(num_retries=5)
                        break
                    except Exception as e:
                        if attempt >= 20:
                            raise
                        logger.warning("Drive upload chunk retry %d/20 for %s: %s", attempt, batch_id, e)
                        import time
                        time.sleep(min(25, 2 ** min(attempt, 4)))
                if status:
                    logger.debug("Uploading %s: %d%%", batch_id, int(status.progress() * 100))

            file_id = response.get("id")
            uploaded_size = int(response.get("size", 0))

            if uploaded_size != expected_size and uploaded_size > 0:
                logger.warning(
                    "Drive upload size mismatch for %s: local %d, drive %d",
                    batch_id,
                    expected_size,
                    uploaded_size,
                )

            # Also create and upload an archive manifest JSON to archive-manifests folder
            manifest_folder_id = subfolders.get("archive-manifests")
            if manifest_folder_id:
                manifest_payload = {
                    "batch_id": batch_id,
                    "filename": p.name,
                    "file_id": file_id,
                    "size_bytes": uploaded_size,
                    "md5": response.get("md5Checksum"),
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                }
                manifest_meta = {
                    "name": f"{batch_id}.manifest.json",
                    "parents": [manifest_folder_id],
                }
                import io
                from googleapiclient.http import MediaIoBaseUpload
                manifest_io = io.BytesIO(json.dumps(manifest_payload, indent=2).encode("utf-8"))
                manifest_media = MediaIoBaseUpload(manifest_io, mimetype="application/json")
                service.files().create(body=manifest_meta, media_body=manifest_media, fields="id").execute()

            logger.info("Successfully uploaded batch %s to Google Drive (file_id=%s)", batch_id, file_id)
            return {
                "file_id": file_id,
                "folder_id": folder_id,
                "size_bytes": uploaded_size,
                "web_view_link": response.get("webViewLink"),
            }
        finally:
            if should_close:
                db.close()

    def download_batch(
        self,
        drive_file_id: str,
        destination_path: str,
        db: Optional[Session] = None,
    ) -> str:
        """Download archived batch from Google Drive for index recovery or auditing."""
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        creds = self.get_credentials(db=db)
        if not creds:
            raise PermissionError("Google Drive is not connected.")

        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        request = service.files().get_media(fileId=drive_file_id)

        import io
        with open(dest, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=5 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        logger.info("Downloaded Drive file %s to %s", drive_file_id, destination_path)
        return str(dest)


_gdrive_service: Optional[GoogleDriveStorageService] = None


def get_google_drive_service() -> GoogleDriveStorageService:
    global _gdrive_service
    if _gdrive_service is None:
        _gdrive_service = GoogleDriveStorageService()
    return _gdrive_service
