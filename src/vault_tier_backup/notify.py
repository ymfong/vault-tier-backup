import logging
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def _build_body(zip_names, backup_type, num_files=None, total_size=None):
    body = f"Backup type: {backup_type}\nBackup file(s): {zip_names}\n"
    if num_files is not None:
        body += f"Total files: {num_files}\nTotal size: {total_size} bytes\n"
    body += "\nSee logs for details."
    return body


def send_email_smtp(
    smtp_server, smtp_port, from_addr, to_addr, password, zip_names, backup_type,
    num_files=None, total_size=None,
):
    try:
        msg = EmailMessage()
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = f"Backup Notification: {backup_type}"
        msg.set_content(_build_body(zip_names, backup_type, num_files, total_size))
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(from_addr, password)
            server.send_message(msg)
        logger.info(f"Email sent to {to_addr}")
    except Exception as e:
        logger.error(f"Email failed: {e}")


def send_email_outlook(to_addr, zip_names, backup_type, num_files=None, total_size=None):
    import win32com.client as win32  # lazy: only needed for this backend, Windows+Outlook only

    try:
        outlook = win32.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem
        mail.To = ";".join(to_addr) if isinstance(to_addr, list) else to_addr
        mail.Subject = f"Backup Notification: {backup_type}"
        mail.HTMLBody = f"""
        <html>
        <body>
            <h2>Backup Notification: {backup_type.capitalize()}</h2>
            <p>The backup process completed successfully.</p>
            <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">
                <tr style="background-color: #f2f2f2;">
                    <th>Backup File</th>
                    <th>Total Files</th>
                    <th>Total Size (bytes)</th>
                </tr>
                <tr>
                    <td>{zip_names}</td>
                    <td>{num_files if num_files is not None else '-'}</td>
                    <td>{total_size if total_size is not None else '-'}</td>
                </tr>
            </table>
            <p>See logs for more details.</p>
        </body>
        </html>
        """
        mail.Send()
        logger.info(f"Email sent to {to_addr}")
    except Exception as e:
        logger.error(f"Email failed: {e}")


def notify(config, email_password, zip_names, backup_type, num_files=None, total_size=None, dry_run=False):
    control = config["control"]
    if dry_run or not control.get("email_enabled", False):
        return

    email_cfg = config["email"]
    method = email_cfg.get("method", "smtp")

    if method == "outlook":
        send_email_outlook(email_cfg["to"], zip_names, backup_type, num_files, total_size)
    else:
        send_email_smtp(
            email_cfg.get("smtp_server", "smtp.office365.com"),
            email_cfg.get("smtp_port", 587),
            email_cfg["from"],
            email_cfg["to"],
            email_password,
            zip_names,
            backup_type,
            num_files,
            total_size,
        )
