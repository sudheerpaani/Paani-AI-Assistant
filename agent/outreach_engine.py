import os
import time
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("OutreachEngine")

class OutreachEngine:
    """
    Automated Email Outreach & RFQ Engine for Paani 2.0.
    Handles formal supplier inquiry generation, attachment of generated PDF Purchase Orders,
    local .eml draft saving in ./exports/, and secure SMTP email dispatch.
    """

    def __init__(self, exports_dir: Optional[str] = None):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.exports_dir = exports_dir if exports_dir else os.path.join(self.base_dir, "exports")
        os.makedirs(self.exports_dir, exist_ok=True)
        
        self.smtp_host = os.getenv("PAANI_SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("PAANI_SMTP_PORT", "587"))
        self.smtp_user = os.getenv("PAANI_SMTP_USER", "")
        self.smtp_pass = os.getenv("PAANI_SMTP_PASS", "")

    def compose_rfq_template(
        self,
        vendor_name: str,
        po_ref: str,
        item_name: str = "Microchip Component",
        quantity: str = "500 Units",
        target_price: str = "$12.50",
        shipping_terms: str = "3 Days Air Express"
    ) -> Dict[str, str]:
        """
        Compose subject and body for a formal supplier RFQ email inquiry.
        """
        subject = f"[RFQ INQUIRY] Procurement Order - {item_name} (Ref: {po_ref})"
        body = (
            f"Dear Sales & Procurement Team at {vendor_name},\n\n"
            f"We are issuing a formal Request for Quotation (RFQ) for the procurement of {item_name}.\n\n"
            f"ORDER PARAMETERS:\n"
            f"- Purchase Order Ref: {po_ref}\n"
            f"- Target Quantity: {quantity}\n"
            f"- Target Unit Price: {target_price} / unit\n"
            f"- Preferred Logistics: {shipping_terms}\n\n"
            f"Please find our attached official Purchase Order specification document ({po_ref}.pdf) for terms, "
            f"tax compliance details, and billing instructions.\n\n"
            f"Kindly confirm stock availability and lead time by replying to this transmission.\n\n"
            f"Best regards,\n"
            f"Autonomous Procurement Engine | Paani 2.0 Command Center\n"
            f"Ref Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        return {"subject": subject, "body": body}

    def send_rfq_email(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        attachment_path: Optional[str] = None,
        draft_only: bool = True
    ) -> Dict[str, Any]:
        """
        Draft or send an RFQ email with optional PDF PO attachment.
        If draft_only or SMTP credentials are missing, saves an .eml draft file into ./exports/.
        """
        msg = MIMEMultipart()
        sender_email = self.smtp_user if self.smtp_user else "procurement@paani.ai"
        msg["From"] = f"Paani Procurement Engine <{sender_email}>"
        msg["To"] = recipient_email
        msg["Subject"] = subject

        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        # Attach PDF PO if provided
        if attachment_path and os.path.exists(attachment_path):
            try:
                filename = os.path.basename(attachment_path)
                with open(attachment_path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=filename)
                part["Content-Disposition"] = f'attachment; filename="{filename}"'
                msg.attach(part)
                logger.info(f"Attached PDF PO: {filename}")
            except Exception as e:
                logger.error(f"Failed to attach file {attachment_path}: {e}")

        # 1. Draft Mode / Fallback: Save .eml file
        if draft_only or not (self.smtp_user and self.smtp_pass):
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            eml_filename = f"RFQ_Outreach_{timestamp}.eml"
            eml_path = os.path.join(self.exports_dir, eml_filename)
            try:
                with open(eml_path, "w", encoding="utf-8") as f:
                    f.write(msg.as_string())
                logger.info(f"RFQ Email Draft saved to: {eml_path}")
                return {
                    "success": True,
                    "status": "DRAFT_SAVED",
                    "recipient": recipient_email,
                    "eml_path": eml_path,
                    "filename": eml_filename,
                    "message": f"RFQ Email draft safely generated in exports directory."
                }
            except Exception as e:
                logger.error(f"Failed to save .eml draft: {e}")
                return {"success": False, "status": "ERROR", "error": str(e)}

        # 2. Live SMTP Dispatch Mode
        try:
            logger.info(f"Connecting to SMTP Server {self.smtp_host}:{self.smtp_port}...")
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            logger.info(f"RFQ Email successfully dispatched to {recipient_email}")
            return {
                "success": True,
                "status": "DISPATCHED",
                "recipient": recipient_email,
                "message": f"RFQ Email successfully dispatched to {recipient_email}."
            }
        except Exception as e:
            logger.error(f"SMTP dispatch failed: {e}")
            # Fall back to draft saving
            return self.send_rfq_email(recipient_email, subject, body_text, attachment_path, draft_only=True)
