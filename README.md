

```markdown
# TaxTruth AI Tax Platform

TaxTruth is an AI-assisted tax strategy platform. It reads uploaded tax return PDFs, detects the tax form type, extracts important tax facts, cross-checks extracted data, fills a client questionnaire, and generates CPA-style tax strategy recommendations.

The long-term goal is to support these IRS return types:

- **Form 1040** — Individual income tax return
- **Form 1065** — Partnership return
- **Form 1120** — C Corporation return
- **Form 1120-S** — S Corporation return

---

## Current Status

| Form | Status |
|---|---|
| **1120-S** | Working end-to-end |
| **1040** | Working with text extraction, vision extraction, cross-check, and review workflow |
| **1065** | Detection, extraction, questionnaire merge, strategy report working |
| **1120** | Pending |

---

## 1. What This System Does

The system turns a tax return PDF into a CPA-review strategy report.

### High-Level Flow

```text
User uploads PDF
↓
System detects form type
↓
System extracts tax facts
↓
System cross-checks text extraction and vision extraction
↓
Trusted fields auto-fill questionnaire
↓
Conflicting fields go to human review
↓
User approves/fixes fields
↓
Questionnaire becomes client profile
↓
Rule engine finds obvious tax strategies
↓
AI matcher finds additional approved strategies
↓
Final TaxTruth report is generated
```

### Important Product Rule

```text
AI should never guess tax numbers.
If a field is uncertain or conflicting, it must be marked for review.
```

---

## 2. Core Principles

### Accuracy Over Guessing

If a value cannot be confidently extracted, it should stay blank/null or be marked:

```text
requires_review = true
```

### Transparency

Every extracted value should include:

- Source form
- Source line
- Extraction method
- Confidence score
- Notes

### User Control

No strategy counts toward totals until the user marks it:

```text
Recommend
```

Strategies can also be:

- Recommend
- Decline
- Defer
- Undecided

---

## 3. Current Tech Stack

| Layer | Tool |
|---|---|
| Backend API | FastAPI |
| Language | Python |
| PDF text extraction | pypdf |
| PDF page rendering | PyMuPDF |
| AI text extraction | OpenAI/OpenRouter-compatible chat API |
| Vision extraction | OpenAI/OpenRouter vision model |
| Local dev UI | HTML/CSS/JavaScript served by FastAPI |
| Future database | PostgreSQL |
| Future storage | S3 |
| Future vector database | Pinecone |
| Future OCR/layout | Google Document AI |

---

## 4. Main User Flow

### Step 1 — Upload PDF

The user uploads a tax return PDF.

The backend receives the file through:

```text
main.py
```

---

### Step 2 — Detect Form Type

The system determines whether the return is:

```text
1040
1065
1120
1120-S
```

The detector must identify the **primary tax return**, not just embedded schedules or K-1 references.

Example:

```text
A 1040 package may contain a K-1.
The primary form is still 1040.
```

---

### Step 3 — Extract Facts

The system extracts important tax values into structured extraction cards.

Example:

```json
{
  "field_name": "gross_receipts",
  "value": 1860404,
  "source_form": "Form 1120-S",
  "source_line": "Line 1a",
  "confidence": 0.95,
  "requires_review": false
}
```

---

### Step 4 — Cross-Check Text and Vision

For complex PDFs, the system compares:

```text
PDF text extraction
vs
Vision extraction from rendered page images
```

If both match:

```text
field is trusted
```

If they conflict:

```text
field requires human review
```

---

### Step 5 — Safe Questionnaire Merge

Only trusted fields are auto-merged into the questionnaire.

Conflicting fields are not auto-filled.

---

### Step 6 — Human Review

The user reviews fields that need attention.

Example:

```json
{
  "field_name": "amount_owed",
  "text_value": 0,
  "vision_value": 196834,
  "status": "CONFLICT_REVIEW_REQUIRED"
}
```

The user chooses the correct value before it enters the questionnaire.

---

### Step 7 — Strategy Matching

The system uses two layers:

1. **Deterministic CPA rules**
2. **AI strategy matcher**

The AI matcher can only choose from approved strategy names.

---

### Step 8 — Final Report

The final report includes:

- Extracted forms
- Questionnaire data
- Extraction cards
- Recommended strategies
- Declined strategies
- Deferred strategies
- Undecided strategies
- Estimated savings totals
- Guardrails
- Source summary

---

## 5. Important API Endpoints

Run the server:

```bash
python main.py
```

Open the app:

```text
http://127.0.0.1:8000
```

Open API docs:

```text
http://127.0.0.1:8000/docs
```

### Health Check

```http
GET /health
```

Expected response:

```json
{
  "status": "ok",
  "service": "AI Tax Platform"
}
```

---

### Detect Tax Form

```http
POST /detect-form
```

Uploads a PDF and returns the detected primary form type.

---

### Extract Facts

```http
POST /extract-facts
```

Extracts structured fields from the PDF.

---

### Cross-Check Extraction

```http
POST /cross-check-extraction
```

Compares text extraction with vision extraction.

---

### Cross-Check and Merge Questionnaire

```http
POST /cross-check-and-merge-questionnaire
```

Only auto-merges fields where text and vision agree.

---

### Apply Reviewed Fields

```http
POST /apply-reviewed-fields
```

Accepts user-approved fields and merges them into the questionnaire.

---

### Generate Final Report

```http
POST /generate-final-report
```

Runs the PDF-based strategy report pipeline.

---

### Generate Report From Reviewed Questionnaire

```http
POST /generate-report-from-reviewed-questionnaire
```

Generates strategies from a reviewed questionnaire instead of raw extraction.

---

## 6. File-by-File Explanation

### `main.py`

Main FastAPI app.

Responsibilities:

- Serves the frontend UI
- Handles uploads
- Exposes API endpoints
- Connects all pipeline files together

Important endpoints:

- `/detect-form`
- `/extract-facts`
- `/cross-check-extraction`
- `/cross-check-and-merge-questionnaire`
- `/apply-reviewed-fields`
- `/generate-final-report`
- `/generate-report-from-reviewed-questionnaire`

---

### `index.html`

Frontend UI.

Responsibilities:

- Lets the user upload a PDF
- Shows a guided workflow
- Calls backend endpoints
- Displays clean summaries
- Displays raw JSON for developers

Current UI actions:

- Detect
- Extract
- Cross-check
- Safe merge
- Final report
- Recommend all test

---

### `pdf_extractor.py`

PDF extraction layer.

Responsibilities:

- Reads PDF files
- Extracts raw text using `pypdf`
- Renders page images using `PyMuPDF`
- Returns page count, text, file hash, and image paths

Used by:

- `fact_extractor.py`
- `vision_extractor.py`
- `cross_check_engine.py`

---

### `form_detector.py`

Tax form classifier.

Responsibilities:

- Detects the primary tax form
- Detects form candidates and schedules
- Handles embedded forms inside larger tax packages

Important behavior:

```text
A full 1040 package may contain K-1s or 1120-S references,
but the primary form should still be 1040.
```

```text
A 1065 package may contain embedded 1120-S text,
but the primary form should still be 1065.
```

The detector uses first-page/header override to avoid wrong primary classification.

---

### `fact_extractor.py`

Structured extraction layer.

Responsibilities:

- Converts PDF text into extraction cards
- Extracts known fields for supported forms
- Adds source lines and confidence scores
- Flags uncertain fields

Current support:

- 1120-S extraction
- 1040 extraction
- 1065 extraction

Important note:

```text
1040 extraction can be difficult from raw PDF text alone.
Complex 1040 packages should use cross-checking.
```

---

### `vision_extractor.py`

Vision extraction layer.

Responsibilities:

- Renders PDF pages as images
- Sends page images to a vision model
- Extracts visible fields from Form 1040 page images

Current provider:

```text
OpenAI/OpenRouter-compatible vision model
```

Future improvement:

```text
Google Document AI for OCR/layout extraction
```

---

### `cross_check_engine.py`

Accuracy layer.

Responsibilities:

- Compares text-extracted values with vision-extracted values
- Trusts values only when sources agree
- Marks conflicts for human review

Possible statuses:

```text
MATCHED_TEXT_AND_VISION
CONFLICT_REVIEW_REQUIRED
TEXT_ONLY_REVIEW_REQUIRED
VISION_ONLY_REVIEW_REQUIRED
MISSING
```

This file is critical for CPA-safe extraction.

---

### `questionnaire.py`

Questionnaire schema and merge logic.

Responsibilities:

- Defines default personal questionnaire
- Defines default financial questionnaire
- Maps extracted fields to questionnaire fields
- Merges only approved/trusted fields
- Records merge events

Example mappings:

```text
wages → clientAnnualCompensation
total_income → householdIncome
officer_compensation → sCorpOfficerComp
shareholder_distributions → sCorpDistributions
gross_receipts → managementCompanyRevenue
ordinary_business_income → householdIncome
```

Important rule:

```text
Do not overwrite user-entered values unless overwrite is explicitly allowed.
```

---

### `strategy_rules.py`

Deterministic CPA rule engine.

Responsibilities:

- Finds high-confidence strategies using hardcoded rules
- Runs before the AI matcher
- Provides explainable source rules

Current support:

- 1120-S rules
- 1040 rules
- 1065 rules

Examples:

```text
1120-S + officer compensation + distributions
→ S-Corp Reasonable Compensation Planning
```

```text
1040 + QBI deduction
→ QBI Deduction Optimization
```

```text
1065 + ordinary business income
→ QBI Deduction Optimization
```

---

### `strategy_ai_matcher.py`

AI strategy matcher.

Responsibilities:

- Sends questionnaire + facts + rule results to AI
- AI selects additional strategies
- AI can only choose from approved strategy names
- Rejects invented strategies

Guardrails:

```json
{
  "approved_strategy_list_enforced": true,
  "form_policy_enforced": true,
  "no_invented_strategy_names": true
}
```

---

### `report_generator.py`

Final report builder.

Responsibilities:

- Combines extraction cards
- Combines questionnaire
- Combines rule strategies
- Combines AI matches
- Applies user decisions
- Calculates savings totals only for recommended strategies

Important rule:

```text
Savings totals count only if decision = recommend.
```

Without decisions:

```text
Strategies go to undecidedStrategies.
Totals remain 0.
```

With recommend decisions:

```text
Strategies go to recommendedStrategies.
Totals increase.
```

---

### `ai_report_generator.py`

Legacy AI report generator.

Responsibilities:

- Older rich AI-generated report flow
- Useful for testing CPA-style language
- Not the preferred final architecture

Preferred current flow:

```text
pdf_extractor
→ form_detector
→ fact_extractor
→ cross_check_engine
→ questionnaire
→ strategy_rules
→ strategy_ai_matcher
→ report_generator
```

---

## 7. Current Working Form Support

### Form 1120-S

Status:

```text
Working end-to-end
```

Extracted values include:

- Gross receipts
- Ordinary business income
- Officer compensation
- Shareholder distributions
- Retained earnings
- Section 179
- Form 4562 reference status

Strategy examples:

- S-Corp Reasonable Compensation Planning
- Retirement Plan Design
- Defined Benefit / Cash Balance Plan
- Accountable Plan
- Dental Equipment Depreciation Planning
- QBI Deduction Optimization

---

### Form 1040

Status:

```text
Working with cross-check and review workflow
```

Supports:

- Simple 1040 extraction
- Complex 1040 package detection
- Text vs vision cross-check
- Safe questionnaire merge
- Reviewed-field approval

Important behavior:

```text
Complex PDFs may produce conflicting text and vision values.
The system does not trust conflicts.
```

---

### Form 1065

Status:

```text
Working for current test package
```

Extracted values include:

- Total assets
- Number of K-1s
- Gross receipts
- Cost of goods sold
- Gross profit
- Total income
- Total deductions
- Ordinary business income

Strategy examples:

- QBI Deduction Optimization
- Entity Structure Review
- Retirement Plan Design
- Tax Planning Fee Deduction

---

### Form 1120

Status:

```text
Pending
```

Needs:

- Detection test with real 1120 PDF
- Extraction card
- Questionnaire mappings
- Deterministic rules
- AI strategy policy refinements

---

## 8. Environment Variables

Create `.env` in the project root.

Example OpenAI setup:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
OPENAI_VISION_MODEL=gpt-4o-mini
```

Optional OpenRouter setup:

```env
OPENROUTER_API_KEY=your_key_here
OPENROUTER_API_URL=https://openrouter.ai/api/v1/chat/completions
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_VISION_MODEL=openai/gpt-4o-mini
```

Do not commit `.env`.

---

## 9. Installation

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
python main.py
```

Open the frontend:

```text
http://127.0.0.1:8000
```

Open API docs:

```text
http://127.0.0.1:8000/docs
```

---

## 10. Git Ignore

Make sure `.gitignore` includes:

```gitignore
.env
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
.DS_Store
.idea/
taxtruth_pdf_pages_*/
*.log
```

---

## 11. Current Development Status

Completed:

- PDF text extraction
- PDF image rendering
- Form detection
- 1120-S extraction/report flow
- 1040 extraction/cross-check/review flow
- 1065 extraction/report flow
- Questionnaire merge
- Strategy rules
- AI strategy matcher
- Final report generator
- Frontend `index.html`

In progress / next:

- 1120 C-Corp support
- Review UI for conflicted fields
- Better schedule-specific extraction cards
- Google Document AI integration
- Persistent database
- S3 file storage
- User accounts
- Strategy knowledge base / Pinecone

---

## 12. Next Developer Tasks

Recommended order:

1. Add Form 1120 C-Corp support
2. Add UI for reviewing conflicting fields
3. Store uploaded PDFs and extraction results in a database
4. Add S3 file storage
5. Add Google Document AI OCR/layout extraction
6. Add schedule-specific extraction cards:
   - Schedule A
   - Schedule B
   - Schedule D
   - Schedule E
   - Schedule K-1
   - Form 4562
7. Add Pinecone strategy knowledge base
8. Build production React/Next.js frontend
9. Add authentication and client records

---

## 13. Key Product Rule

This is the most important rule in the whole project:

```text
If the system is not sure, it must not guess.
It must ask the user to review.
```

This is what makes the system CPA-safe.

---

## 14. Summary

TaxTruth is becoming a CPA-review tax strategy engine.

The system can already:

- Read PDFs
- Detect tax forms
- Extract tax facts
- Cross-check text and vision
- Fill questionnaires safely
- Run deterministic tax strategy rules
- Use AI to match approved strategies
- Generate final reports

The end goal is a production platform where users upload tax returns and receive clear, reviewed, CPA-style strategy recommendations with full transparency and no hidden guessing.
```