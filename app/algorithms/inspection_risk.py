"""
Inspection Risk Algorithm

Simple, deterministic risk scoring for material inspections.
All risk calculation logic is isolated in this file.
"""
from datetime import date
from typing import Optional


def calculate_inspection_risk(material, keuring, today: date) -> dict:
    """
    Calculate inspection risk score for a material and its keuring.
    
    Args:
        material: Material model instance
        keuring: Keuringstatus model instance
        today: Current date (date object)
    
    Returns:
        {
            "risk_score": int (0-100),
            "risk_level": "low" | "medium" | "high" | "critical",
            "risk_explanation": str
        }
    """
    risk_score = 0
    explanation_parts = []
    
    # 1️⃣ Urgency (0-60 points)
    urgency_score = 0
    if keuring and keuring.volgende_controle:
        days = (keuring.volgende_controle - today).days
        
        if days < 0:
            urgency_score = 60
            explanation_parts.append(f"{abs(days)} dagen te laat")
        elif days == 0:
            urgency_score = 50
            explanation_parts.append("vandaag")
        elif 1 <= days <= 7:
            urgency_score = 40
            explanation_parts.append(f"binnen {days} dagen")
        elif 8 <= days <= 30:
            urgency_score = 20
            explanation_parts.append(f"binnen {days} dagen")
        else:
            urgency_score = 0
    else:
        urgency_score = 0
    
    risk_score += urgency_score
    
    # 2️⃣ History (0-25 points)
    history_score = 0
    if material:
        # Get latest KeuringHistoriek record for this material
        try:
            from models import KeuringHistoriek
            latest_history = (
                KeuringHistoriek.query
                .filter_by(material_id=material.id)
                .order_by(KeuringHistoriek.keuring_datum.desc())
                .first()
            )
            
            if latest_history:
                resultaat = (latest_history.resultaat or "").lower()
                if resultaat == "afgekeurd":
                    history_score = 25
                    explanation_parts.append("laatste keuring afgekeurd")
                elif resultaat == "voorwaardelijk":
                    history_score = 15
                    explanation_parts.append("laatste keuring voorwaardelijk")
        except Exception:
            # Safe fallback if model doesn't exist or query fails
            pass
    
    risk_score += history_score
    
    # 3️⃣ Active usage (0-15 points)
    usage_score = 0
    if material:
        try:
            from models import MaterialUsage
            # Check if material has active usage
            active_usage = MaterialUsage.query.filter_by(
                material_id=material.id,
                is_active=True
            ).first()
            
            if active_usage:
                usage_score = 15
                explanation_parts.append("actief in gebruik")
        except Exception:
            # Safe fallback if model doesn't exist or query fails
            pass
    
    risk_score += usage_score
    
    # 4️⃣ Clamp to 0-100
    risk_score = max(0, min(100, risk_score))
    
    # Determine risk level
    if risk_score >= 75:
        risk_level = "critical"
    elif risk_score >= 50:
        risk_level = "high"
    elif risk_score >= 25:
        risk_level = "medium"
    else:
        risk_level = "low"
    
    # Build explanation
    if explanation_parts:
        risk_explanation = ", ".join(explanation_parts)
    else:
        risk_explanation = "Geen bijzondere risicofactoren"
    
    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_explanation": risk_explanation
    }

