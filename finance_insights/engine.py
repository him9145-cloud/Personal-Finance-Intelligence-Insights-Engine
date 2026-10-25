"""Transaction cleanup, financial metrics, anomaly detection, and reporting."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ALIASES = {
    "date": ("date", "transaction date", "posted date", "posting date", "trans date"),
    "description": ("description", "merchant", "payee", "name", "details", "transaction description"),
    "amount": ("amount", "transaction amount", "value"),
    "debit": ("debit", "withdrawal", "money out", "charges"),
    "credit": ("credit", "deposit", "money in", "credits"),
    "type": ("type", "transaction type", "debit/credit", "direction"),
    "category": ("category", "transaction category"),
}

CATEGORY_RULES = {
    "Housing": ("rent", "mortgage", "landlord", "property"),
    "Utilities": ("electric", "power", "water", "gas bill", "internet", "broadband", "utility"),
    "Groceries": ("grocery", "supermarket", "market", "whole foods", "trader joe", "aldi", "costco"),
    "Dining": ("restaurant", "cafe", "coffee", "doordash", "ubereats", "grubhub", "food delivery"),
    "Transport": ("uber", "lyft", "transit", "metro", "train", "parking", "fuel", "gas station"),
    "Shopping": ("amazon", "walmart", "target", "clothing", "shop", "store"),
    "Healthcare": ("pharmacy", "medical", "health", "doctor", "dental", "clinic"),
    "Insurance": ("insurance", "premium"),
    "Subscriptions": ("netflix", "spotify", "hulu", "subscription", "icloud", "adobe", "gym"),
    "Travel": ("airline", "hotel", "airbnb", "booking.com", "flight", "resort"),
    "Income": ("payroll", "salary", "direct deposit", "interest", "dividend"),
    "Transfer": ("transfer", "payment thank you", "credit card payment", "venmo", "zelle", "paypal"),
}
FIXED_CATEGORIES = {"Housing", "Utilities", "Insurance"}


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()


def _find_column(columns: Iterable[str], aliases: tuple[str, ...]) -> str | None:
    normalized = {_key(c): c for c in columns}
    for alias in aliases:
        if _key(alias) in normalized:
            return normalized[_key(alias)]
    return None


def _money(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.strip().str.replace(r"[,$£€₹\s]", "", regex=True)
    negative = cleaned.str.match(r"^\(.*\)$")
    cleaned = cleaned.str.replace(r"[()]", "", regex=True)
    values = pd.to_numeric(cleaned, errors="coerce")
    return values.where(~negative, -values)


def _merchant(value: object) -> str:
    text = str(value).strip()
    text = re.sub(r"\b(card|debit|credit|purchase|pos|transaction)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(\d{4,}|\d{2}/\d{2})\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_*#")
    return text.title() if text else "Unknown"


def categorize(merchant: str, existing: object = None, is_income: bool = False) -> str:
    if existing is not None and not pd.isna(existing) and str(existing).strip():
        return str(existing).strip().title()
    if is_income:
        return "Income"
    text = merchant.lower()
    for category, terms in CATEGORY_RULES.items():
        if category == "Income":
            continue
        if any(term in text for term in terms):
            return category
    return "Other"


def load_transactions(path: str | Path, dayfirst: bool = False) -> pd.DataFrame:
    """Read a bank CSV and normalize common export column names."""
    raw = pd.read_csv(path)
    raw.columns = [str(c).strip() for c in raw.columns]
    found = {name: _find_column(raw.columns, names) for name, names in ALIASES.items()}
    if not found["date"] or not found["description"]:
        raise ValueError("CSV needs a date column and a description/merchant column.")
    if not found["amount"] and not (found["debit"] or found["credit"]):
        raise ValueError("CSV needs an amount column or debit and/or credit columns.")

    df = pd.DataFrame(index=raw.index)
    df["date"] = pd.to_datetime(raw[found["date"]], errors="coerce", dayfirst=dayfirst)
    df["merchant"] = raw[found["description"]].fillna("Unknown").map(_merchant)
    if found["amount"]:
        amount = _money(raw[found["amount"]])
        if found["type"]:
            direction = raw[found["type"]].fillna("").astype(str).str.lower()
            debit = direction.str.contains(r"debit|expense|withdraw|purchase|payment", regex=True)
            credit = direction.str.contains(r"credit|income|deposit|refund", regex=True)
            amount = amount.abs().where(~debit, -amount.abs()).where(~credit, amount.abs())
        df["amount"] = amount
    else:
        debits = _money(raw[found["debit"]]) if found["debit"] else pd.Series(0.0, index=raw.index)
        credits = _money(raw[found["credit"]]) if found["credit"] else pd.Series(0.0, index=raw.index)
        df["amount"] = credits.fillna(0).abs() - debits.fillna(0).abs()

    df["source_category"] = raw[found["category"]] if found["category"] else None
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    # Rows without a usable date or amount cannot contribute to time-based metrics.
    df = df.dropna(subset=["date", "amount"]).copy()
    df = df[df["amount"].abs() > 0].copy()
    df["type"] = np.where(df["amount"] >= 0, "Income", "Expense")
    df["category"] = [categorize(m, c, a >= 0) for m, c, a in zip(df.merchant, df.source_category, df.amount)]
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["spend_type"] = np.where(df.category.isin(FIXED_CATEGORIES), "Fixed", "Discretionary")
    return df.sort_values(["date", "merchant"]).reset_index(drop=True)


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for month, group in df.groupby("month", sort=True):
        income = float(group.loc[group.amount > 0, "amount"].sum())
        expenses = float(-group.loc[group.amount < 0, "amount"].sum())
        rows.append({"month": month, "income": income, "spending": expenses,
                     "net_savings": income - expenses,
                     "net_savings_rate_pct": (100 * (income - expenses) / income) if income else np.nan,
                     "fixed_spending": float(-group.loc[(group.amount < 0) & (group.spend_type == "Fixed"), "amount"].sum()),
                     "discretionary_spending": float(-group.loc[(group.amount < 0) & (group.spend_type == "Discretionary"), "amount"].sum())})
    out = pd.DataFrame(rows)
    out["mom_spending_growth_pct"] = out.spending.pct_change().replace([np.inf, -np.inf], np.nan) * 100
    return out


def category_summary(df: pd.DataFrame) -> pd.DataFrame:
    expenses = df[df.amount < 0].copy()
    if expenses.empty:
        return pd.DataFrame(columns=["category", "spending", "share_pct", "transaction_count"])
    result = expenses.assign(spending=-expenses.amount).groupby("category", as_index=False).agg(
        spending=("spending", "sum"), transaction_count=("amount", "size"))
    total = result.spending.sum()
    result["share_pct"] = result.spending / total * 100 if total else 0
    return result.sort_values("spending", ascending=False)


def detect_anomalies(df: pd.DataFrame, z_threshold: float = 3.0) -> pd.DataFrame:
    """Flag large outlier expenses and recurring merchant charges."""
    expenses = df[df.amount < 0].copy()
    if expenses.empty:
        return pd.DataFrame(columns=list(df.columns) + ["anomaly_reason"])
    vals = -expenses.amount
    mean, std = vals.mean(), vals.std(ddof=0)
    expenses["anomaly_reason"] = ""
    if std > 0:
        expenses.loc[(vals - mean) / std >= z_threshold, "anomaly_reason"] = "Unusually large expense (Z-score)"
    # IQR fences provide a robust fallback for skewed or small samples.
    q1, q3 = vals.quantile([0.25, 0.75])
    fence = q3 + 1.5 * (q3 - q1)
    expenses.loc[(vals > fence) & (expenses.anomaly_reason == ""), "anomaly_reason"] = "Unusually large expense (IQR)"
    for merchant, group in expenses.groupby("merchant"):
        monthly = group.groupby(group.date.dt.to_period("M")).size()
        if len(monthly) >= 2 and (monthly >= 1).sum() >= 2:
            idx = group.index
            expenses.loc[idx[expenses.loc[idx, "anomaly_reason"].eq("")], "anomaly_reason"] = "Repeat merchant charge; review subscription"
    return expenses[expenses.anomaly_reason.ne("")].sort_values("date").reset_index(drop=True)


def make_charts(df: pd.DataFrame, monthly: pd.DataFrame, categories: pd.DataFrame, out_dir: Path) -> list[str]:
    plt.style.use("seaborn-v0_8-whitegrid")
    paths = []
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(monthly.month, monthly.spending, marker="o", label="Spending", color="#dc6b4e")
    ax.plot(monthly.month, monthly.income, marker="o", label="Income", color="#347a72")
    ax.set(title="Monthly income and spending", ylabel="Amount", xlabel="Month")
    ax.tick_params(axis="x", rotation=35); ax.legend(); fig.tight_layout()
    path = out_dir / "monthly_trend.png"; fig.savefig(path, dpi=160); plt.close(fig); paths.append(path.name)
    if not categories.empty:
        fig, ax = plt.subplots(figsize=(8, 5))
        top = categories.head(8).sort_values("spending")
        ax.barh(top.category, top.spending, color="#527b9b")
        ax.set(title="Spending by category", xlabel="Amount")
        fig.tight_layout(); path = out_dir / "category_spending.png"; fig.savefig(path, dpi=160); plt.close(fig); paths.append(path.name)
    curve = monthly.assign(cumulative_savings=monthly.net_savings.cumsum())
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(curve.month, curve.cumulative_savings, marker="o", color="#7654a1")
    ax.axhline(0, color="black", linewidth=.8); ax.set(title="Cumulative net savings", ylabel="Amount", xlabel="Month")
    ax.tick_params(axis="x", rotation=35); fig.tight_layout()
    path = out_dir / "cumulative_savings.png"; fig.savefig(path, dpi=160); plt.close(fig); paths.append(path.name)
    return paths


def write_report(df: pd.DataFrame, monthly: pd.DataFrame, categories: pd.DataFrame,
                 anomalies: pd.DataFrame, chart_names: list[str], out_path: Path) -> None:
    income, spending = df.loc[df.amount > 0, "amount"].sum(), -df.loc[df.amount < 0, "amount"].sum()
    rate = 100 * (income - spending) / income if income else np.nan
    period = f"{df.date.min():%d %b %Y} to {df.date.max():%d %b %Y}" if len(df) else "No valid transactions"
    lines = ["# Personal Finance Summary", "", f"**Period:** {period}", f"**Transactions analyzed:** {len(df)}", "",
             "## Financial snapshot", "", f"- Total income: {income:,.2f}", f"- Total spending: {spending:,.2f}",
             f"- Net savings: {income - spending:,.2f}", f"- Net savings rate: {rate:.1f}%" if np.isfinite(rate) else "- Net savings rate: unavailable (no income recorded)",
             f"- Flagged transactions: {len(anomalies)}", "", "## Monthly metrics", "",
             "| Month | Income | Spending | Net savings | Savings rate | MoM spending growth |",
             "|---|---:|---:|---:|---:|---:|"]
    for _, row in monthly.iterrows():
        rate_txt = f"{row.net_savings_rate_pct:.1f}%" if pd.notna(row.net_savings_rate_pct) else "—"
        mom_txt = f"{row.mom_spending_growth_pct:+.1f}%" if pd.notna(row.mom_spending_growth_pct) else "—"
        lines.append(f"| {row.month} | {row.income:,.2f} | {row.spending:,.2f} | {row.net_savings:,.2f} | {rate_txt} | {mom_txt} |")
    lines += ["", "## Spending by category", "", "| Category | Spending | Share | Transactions |", "|---|---:|---:|---:|"]
    for _, row in categories.iterrows():
        lines.append(f"| {row.category} | {row.spending:,.2f} | {row.share_pct:.1f}% | {int(row.transaction_count)} |")
    lines += ["", "## Review flags", ""]
    if anomalies.empty:
        lines.append("No transactions were flagged by the current rules.")
    else:
        lines += ["| Date | Merchant | Amount | Reason |", "|---|---|---:|---|"]
        for _, row in anomalies.iterrows():
            lines.append(f"| {row.date:%Y-%m-%d} | {row.merchant} | {-row.amount:,.2f} | {row.anomaly_reason} |")
    lines += ["", "## Charts", ""]
    lines.extend(f"![{Path(name).stem.replace('_', ' ').title()}]({name})" for name in chart_names)
    lines += ["", "## Notes", "", "Savings rate is calculated as (income − spending) / income. MoM growth compares each month with the preceding month. Category rules and anomaly flags are heuristic; review flagged items and confirm bank-specific sign conventions.", ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def analyze(input_path: str | Path, out_dir: str | Path, dayfirst: bool = False) -> dict[str, Path]:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    transactions = load_transactions(input_path, dayfirst=dayfirst)
    if transactions.empty:
        raise ValueError("No valid non-zero transactions with parseable dates were found.")
    monthly, categories = monthly_summary(transactions), category_summary(transactions)
    anomalies = detect_anomalies(transactions)
    tx_path, month_path = out / "cleaned_transactions.csv", out / "monthly_summary.csv"
    category_path, anomaly_path = out / "category_summary.csv", out / "anomalies.csv"
    transactions.drop(columns=["source_category"]).to_csv(tx_path, index=False)
    monthly.to_csv(month_path, index=False); categories.to_csv(category_path, index=False); anomalies.to_csv(anomaly_path, index=False)
    charts = make_charts(transactions, monthly, categories, out)
    report_path = out / "financial_health_report.md"
    write_report(transactions, monthly, categories, anomalies, charts, report_path)
    return {"transactions": tx_path, "monthly": month_path, "categories": category_path,
            "anomalies": anomaly_path, "report": report_path, "charts": out}
