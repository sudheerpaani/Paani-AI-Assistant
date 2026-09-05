import re
import logging
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AdversarialRiskCritic")

class AdversarialRiskCritic:
    """
    Adversarial Risk & Compliance Critic layer in Paani 2.0.
    Audits vendor data, verifies tax entity credentials (GSTIN/UEN), detects pricing anomalies,
    evaluates shipping realism, and recalculates vendor trust scores before decision tree rendering.
    """

    GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
    UEN_PATTERN = r"^[0-9]{8,10}[A-Z]$|^[TSSM0-9]{2}[0-9]{2}[A-Z]{2}[0-9]{4}[A-Z]$"

    def __init__(self):
        logger.info("AdversarialRiskCritic initialized.")

    def audit_vendor_data(
        self,
        vendor: Dict[str, Any],
        market_avg_price: Optional[float] = 18.50,
        contract_target_price: Optional[float] = 12.50
    ) -> Dict[str, Any]:
        """
        Audit a vendor record and return risk breakdown, GST status, and updated trust score.
        """
        vendor_name = vendor.get("name", "Unknown Supplier")
        platform = vendor.get("platform", "Direct Web")
        price_str = str(vendor.get("unit_price", "0")).replace("$", "").replace("₹", "").replace(",", "").strip()
        
        try:
            unit_price = float(price_str)
        except ValueError:
            unit_price = 0.0

        gstin = vendor.get("gstin", "")
        uen = vendor.get("uen", "")
        shipping_speed = vendor.get("shipping_speed", "3-5 Days Standard")
        initial_trust = int(vendor.get("trust_score", 85))

        risk_breakdown: List[str] = []
        deductions = 0
        bonuses = 0
        gst_status = "UNVERIFIED"

        # 1. Entity & Tax Integrity Audit
        if gstin and re.match(self.GSTIN_PATTERN, gstin.upper()):
            gst_status = "VALID"
            risk_breakdown.append(f"GSTIN Verified: {gstin.upper()}")
            bonuses += 10
        elif uen and re.match(self.UEN_PATTERN, uen.upper()):
            gst_status = "VALID"
            risk_breakdown.append(f"Singapore UEN Verified: {uen.upper()}")
            bonuses += 10
        elif "IndiaMart" in platform or "Amazon" in platform or "Singapore" in vendor_name:
            gst_status = "VALID"
            risk_breakdown.append(f"Platform Verified Badge ({platform})")
            bonuses += 5
        else:
            gst_status = "UNVERIFIED"
            risk_breakdown.append("Unverified Business Registration / Tax ID")
            deductions += 10

        # 2. Pricing & Anomaly Audit
        benchmark_price = contract_target_price if contract_target_price else market_avg_price
        if unit_price > 0 and benchmark_price and benchmark_price > 0:
            discount_pct = ((benchmark_price - unit_price) / benchmark_price) * 100
            if discount_pct > 50:
                risk_breakdown.append(f"ANOMALY: Unit price ${unit_price:.2f} is {discount_pct:.0f}% below market target (Counterfeit/Scam Risk)")
                deductions += 30
            elif unit_price <= benchmark_price:
                risk_breakdown.append(f"Margin Optimal: Price ${unit_price:.2f} within safe target range")
                bonuses += 10
            else:
                overcharge_pct = ((unit_price - benchmark_price) / benchmark_price) * 100
                risk_breakdown.append(f"Price Premium: ${unit_price:.2f} (+{overcharge_pct:.0f}% above target rate)")
                deductions += 5

        # 3. Lead Time Realism Audit
        speed_lower = shipping_speed.lower()
        if "same day" in speed_lower or "1 day" in speed_lower or "24 hr" in speed_lower:
            if "air express" in speed_lower or "local" in speed_lower or "domestic" in speed_lower:
                risk_breakdown.append(f"Logistics Confirmed: Fast shipping ({shipping_speed})")
                bonuses += 5
            else:
                risk_breakdown.append(f"LOGISTICS WARNING: Unrealistic 1-day lead time without Air Express tag")
                deductions += 15
        else:
            risk_breakdown.append(f"Logistics Standard: Stated lead time ({shipping_speed})")
            bonuses += 5

        # Calculate final adjusted trust score (clamped 0-100)
        final_score = max(0, min(100, initial_trust + bonuses - deductions))

        # Risk Classification
        if final_score >= 85 and deductions < 15:
            risk_level = "LOW"
        elif final_score >= 65:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"

        audited_vendor = dict(vendor)
        audited_vendor["trust_score"] = final_score
        audited_vendor["risk_level"] = risk_level
        audited_vendor["gst_status"] = gst_status
        audited_vendor["risk_breakdown"] = risk_breakdown

        logger.info(f"Audited {vendor_name}: Risk={risk_level}, Score={final_score}, GST={gst_status}")
        return audited_vendor

    def audit_vendors_list(self, vendors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Audit a list of vendor dicts."""
        return [self.audit_vendor_data(v) for v in vendors]
