# Personal Finance Intelligence & Insights Engine

A small Python CLI that turns bank or credit-card transaction CSV exports into cleaned data, monthly financial metrics, anomaly review flags, charts, and a Markdown report. It runs locally; your transaction data stays in your chosen output folder.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m finance_insights sample_transactions.csv --out finance_output
```

For ambiguous dates such as `03/04/2025`, choose the bank's convention:

```bash
python -m finance_insights transactions.csv --dayfirst --out finance_output
```

## Input format

The engine recognizes common headers for transaction date, description or merchant, amount, debit, credit, transaction type, and category. The minimum input is a date, description, and amount column. Alternatively, provide debit and/or credit columns. Negative amounts are treated as expenses and positive amounts as income. For unsigned amount exports, include a `Type` column with values such as `Debit` or `Credit` so signs can be inferred.

Common date headers include `Date`, `Transaction Date`, and `Posted Date`. Merchant headers include `Description`, `Merchant`, `Payee`, and `Details`. Category values supplied by the bank take precedence over the built-in keyword rules.

## Outputs

- `cleaned_transactions.csv` — standardized dates, merchant names, direction, category, month, and fixed/discretionary label.
- `monthly_summary.csv` — income, spending, net savings, savings rate, month-over-month spending growth, and fixed/discretionary spending.
- `category_summary.csv` — spend and share of total expenses per category.
- `anomalies.csv` — unusually large expenses and repeat merchant charges to review.
- `financial_health_report.md` — readable summary with embedded chart references.
- `monthly_trend.png`, `category_spending.png`, `cumulative_savings.png` — generated visualizations.

## Metric definitions and limitations

Net savings rate is `(income - spending) / income`. MoM spending growth is the percentage change in monthly expenses. Fixed spending is a starter classification for housing, utilities, and insurance; remaining spending is marked discretionary. Merchant categorization uses editable keyword rules and may need adjustment for your bank's descriptions. Repeat merchant charges are review flags, not confirmation of a subscription. Statistical flags use Z-score and IQR thresholds over expense amounts; always verify flagged transactions against the original statement.

Transfers and credit-card payments should be excluded or categorized consistently to avoid double-counting when analyzing linked bank and card exports. Keep source files secure and avoid committing personal transaction data.

## Customize

Edit `CATEGORY_RULES` and `FIXED_CATEGORIES` in `finance_insights/engine.py` to fit your spending. The `analyze()` function can also be imported directly by another Python program.
