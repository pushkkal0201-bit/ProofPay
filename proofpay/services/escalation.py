from datetime import timedelta

from engine.accrual import aging, effective_due, estimate


class EscalationEngine:
    @staticmethod
    def clock(case):
        due = effective_due(case)
        dpd = max(0, (case.as_of - due).days)
        terms = case.terms
        confirmed = bool(
            terms and terms.basis == "msmed" and case.msme_registered is not False
        )
        return (
            due,
            dpd,
            aging(dpd),
            estimate(case, due),
            {
                "eligible": confirmed,
                "registered": case.msme_registered,
                "day_45": str(terms.acceptance + timedelta(days=45))
                if confirmed
                else None,
                "interest_starts_on": str(due + timedelta(days=1)) if terms else None,
                "days_until_due": (due - case.as_of).days,
            },
        )

    @staticmethod
    def decide(case, net, dpd, reasons):
        if net <= 0:
            state = "Credit balance" if net < 0 else "Settled"
        elif reasons:
            state = "Review hold"
        elif dpd == 0:
            state = "Current"
        elif dpd <= 30:
            state = "Reminder"
        elif dpd <= 45:
            state = "Reconciliation"
        elif case.terms and case.terms.basis == "msmed":
            state = "MSE legal review"
        else:
            state = "Manager review"
        actions = {
            "Credit balance": "Reconcile the excess receipt with the buyer account.",
            "Settled": "Close the case after confirming the bank posting.",
            "Current": "Monitor until the contractual due date.",
            "Review hold": "Resolve each flagged item and import a corrected snapshot.",
            "Reminder": "Review a reminder requesting a payment date.",
            "Reconciliation": "Review the evidence packet and request a line-specific response within two calendar days.",
            "MSE legal review": "Prepare a section 18 MSEFC referral assessment for the legal reviewer.",
            "Manager review": "Assign a credit manager to review the contract, dispute history and account terms.",
        }
        return state, actions[state]
