import logging
import time

import msal
import requests

logger = logging.getLogger(__name__)


def get_onedrive_token(client_id, client_secret, tenant_id):
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" in result:
        return result["access_token"]
    raise RuntimeError(f"Failed to get OneDrive token: {result}")


def upload_to_cloud(
    zip_path, zip_name, cloud_platform, client_id, client_secret, tenant_id, upload_path,
    dry_run=False, upload_enabled=True,
):
    if dry_run or not upload_enabled:
        return

    if cloud_platform != "onedrive":
        logger.warning("Only OneDrive upload is currently implemented.")
        return

    token = get_onedrive_token(client_id, client_secret, tenant_id)
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{upload_path}/{zip_name}:/content"

    for attempt in range(3):
        try:
            with open(zip_path, "rb") as f:
                r = requests.put(url, headers=headers, data=f, timeout=60)
            if r.status_code in (200, 201):
                logger.info(f"Uploaded {zip_name} to OneDrive successfully.")
                return
            logger.warning(f"Attempt {attempt + 1} failed: {r.text}")
        except requests.RequestException as e:
            logger.error(f"Attempt {attempt + 1} exception: {e}")
        time.sleep(5)

    logger.error("OneDrive upload failed after 3 attempts.")
