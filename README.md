# TaxTruth AI Tax Platform

TaxTruth is an AI-assisted tax strategy platform. It reads uploaded tax return PDFs, detects the tax form type, extracts important tax facts, cross-checks extracted data, fills a client questionnaire, and generates CPA-style tax strategy recommendations.

The long-term goal is to support these IRS return types:

- Form 1040 — Individual return
- Form 1065 — Partnership return
- Form 1120 — C Corporation return
- Form 1120-S — S Corporation return

Current strongest flows:

- Form 1120-S: working end-to-end
- Form 1040: working with text extraction, vision extraction, cross-check, and review workflow
- Form 1065: detection, extraction, questionnaire merge, strategy report working
- Form 1120: pending

---

## 1. What This System Does

The system turns a tax return PDF into a CPA-review strategy report.

High-level flow:

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
Important product rule:

AI should never guess tax numbers.
If a field is uncertain or conflicting, it must be marked for review.
2. Core Principles
Accuracy over guessing
If a value cannot be confidently extracted, it should stay blank/null or be marked requires_review.

Transparency
Every extracted value should include:

source form
source line
extraction method
confidence
notes
User control
No strategy counts toward totals until the user marks it:

Recommend
Strategies can also be:

Decline
Defer
Undecided
3. Current Tech Stack
Layer	Tool
Backend API	FastAPI
Language	Python
PDF text extraction	pypdf
PDF page rendering	PyMuPDF
AI text extraction	OpenAI/OpenRouter-compatible chat API
Vision extraction	OpenAI/OpenRouter vision model
Local dev UI	HTML/CSS/JavaScript served by FastAPI
Future database	PostgreSQL
Future storage	S3
Future vector DB	Pinecone
Future OCR/layout	Google Document AI
4. Main User Flow
Step 1 — Upload PDF
User uploads a tax return PDF.

The backend receives the file through main.py.

Step 2 — Detect form type
The system determines whether the return is:

1040
1065
1120
1120-S
Step 3 — Extract facts
The system extracts tax facts into structured extraction cards.

Example:

{
  "field_name": "gross_receipts",
  "value": 1860404,
  "source_form": "Form 1120-S",
  "source_line": "Line 1a",
  "confidence": 0.95
}
Step 4 — Cross-check text and vision
For complex PDFs, the system compares:

PDF text extraction
vs
Vision extraction from rendered page images
If they match:

field can be trusted
If they conflict:

field requires human review
Step 5 — Safe questionnaire merge
Only trusted fields are auto-merged into the questionnaire.

Conflicted fields stay out until reviewed.

Step 6 — Manual review
User approves or corrects uncertain fields.

Step 7 — Strategy matching
The system uses:

deterministic CPA rules
AI strategy matcher
The AI can only choose from approved strategy names.

Step 8 — Final report
The final report includes:

extracted forms
questionnaire
extraction cards
recommended strategies
undecided strategies
declined strategies
deferred strategies
savings totals
guardrails
5. Important API Endpoints
Run the server:

python main.py
Open UI:

http://127.0.0.1:8000
Open API docs:

http://127.0.0.1:8000/docs
Health check
GET /health
Returns:

{
  "status": "ok",
  "service": "AI Tax Platform"
}
Detect tax form
POST /detect-form
Uploads a PDF and returns primary form type.

Extract facts
POST /extract-facts
Extracts structured fields from the PDF.

Cross-check extraction
POST /cross-check-extraction
Compares text extraction with vision extraction.

Cross-check and merge questionnaire
POST /cross-check-and-merge-questionnaire
Only auto-merges trusted matched fields.

Apply reviewed fields
POST /apply-reviewed-fields
Accepts user-approved fields and merges them into the questionnaire.

Generate final report
POST /generate-final-report
Runs full PDF-based pipeline and returns final report.

Generate report from reviewed questionnaire
POST /generate-report-from-reviewed-questionnaire
Generates strategies from a reviewed questionnaire.

6. File-by-File Explanation
main.py
Main FastAPI app.

Responsibilities:

serves frontend UI
handles file uploads
exposes API endpoints
connects all pipeline files together
Important endpoints:

/detect-form
/extract-facts
/cross-check-extraction
/cross-check-and-merge-questionnaire
/apply-reviewed-fields
/generate-final-report
/generate-report-from-reviewed-questionnaire
index.html
Frontend UI.

Responsibilities:

lets user upload a PDF
gives guided Apple-style workflow
calls backend endpoints
shows clean summaries
shows raw JSON for developers
Current UI buttons:

Detect
Extract
Cross-check
Safe merge
Final report
Recommend all test
pdf_extractor.py
PDF extraction layer.

Responsibilities:

reads PDF files
extracts raw text using pypdf
renders page images using PyMuPDF
returns page count, text, file hash, and image paths
Used by:

fact_extractor.py
vision_extractor.py
cross_check_engine.py
form_detector.py
Tax form classifier.

Responsibilities:

detects primary tax form
detects candidates and schedules
handles embedded forms inside packages
Important behavior:

A full 1040 package may contain K-1s or 1120-S references,
but primary form should still be 1040.
A 1065 package may contain embedded 1120-S text,
but primary form should still be 1065.
The detector uses first-page/header override to avoid wrong primary classification.

fact_extractor.py
Structured text extraction layer.

Responsibilities:

converts raw PDF text into extraction cards
extracts known fields for supported forms
adds confidence and source lines
flags uncertain fields
Current support:

1120-S extraction
1040 extraction
1065 extraction
Important note:

1040 extraction can use AI schema extraction because 1040 layouts are often hard to parse from raw text alone.

vision_extractor.py
Vision extraction layer.

Responsibilities:

renders PDF pages as images
sends page images to a vision model
extracts visible fields from Form 1040 page images
Currently used mostly for:

1040 page 1
1040 page 2
This is not Google Document AI yet.

Current vision provider:

OpenAI/OpenRouter-compatible vision model
Future improvement:

Google Document AI for OCR/layout
cross_check_engine.py
Accuracy layer.

Responsibilities:

compares text-extracted values to vision-extracted values
returns trusted fields only when text and vision match
marks conflicts as review required
Statuses:

MATCHED_TEXT_AND_VISION
CONFLICT_REVIEW_REQUIRED
TEXT_ONLY_REVIEW_REQUIRED
VISION_ONLY_REVIEW_REQUIRED
MISSING
This file is critical for CPA-safe extraction.

questionnaire.py
Questionnaire schema and merge logic.

Responsibilities:

defines default personal questionnaire
defines default financial questionnaire
maps extracted fields to questionnaire fields
merges only approved/trusted fields
records merge events
Example mappings:

wages → clientAnnualCompensation
total_income → householdIncome
officer_compensation → sCorpOfficerComp
shareholder_distributions → sCorpDistributions
gross_receipts → managementCompanyRevenue
ordinary_business_income → householdIncome
Important rule:

Do not overwrite user-entered values unless overwrite is explicitly allowed.
strategy_rules.py
Deterministic CPA rule engine.

Responsibilities:

finds high-confidence strategies using hardcoded rules
runs before AI
provides explainable source rules
Current rule support:

1120-S
1040
1065
Examples:

1120-S + officer comp + distributions
→ S-Corp Reasonable Compensation Planning
1040 + QBI deduction
→ QBI Deduction Optimization
1065 + ordinary business income
→ QBI Deduction Optimization
strategy_ai_matcher.py
AI strategy matcher.

Responsibilities:

sends questionnaire + facts + rule matches to AI
AI selects additional strategies
AI can only choose from approved strategy names
rejects invented or wrong-form strategies
Important guardrails:

approved_strategy_list_enforced = true
form_policy_enforced = true
no_invented_strategy_names = true
report_generator.py
Final report builder.

Responsibilities:

combines extraction cards
combines questionnaire
combines rule strategies
combines AI matches
applies user decisions
calculates savings totals only for recommended strategies
Important rule:

Savings totals count only if decision = recommend.
Without decisions:

strategies go to undecidedStrategies
totals remain 0
With recommend decisions:

strategies go to recommendedStrategies
totals increase
ai_report_generator.py
Legacy AI report generator.

Responsibilities:

older rich AI-generated report flow
still useful for testing CPA-style strategy wording
not the cleanest architecture now
Current preferred flow:

pdf_extractor
→ form_detector
→ fact_extractor
→ cross_check_engine
→ questionnaire
→ strategy_rules
→ strategy_ai_matcher
→ report_generator
7. Current Working Form Support
Form 1120-S
Status:

working end-to-end
Extracted values include:

gross receipts
ordinary business income
officer compensation
shareholder distributions
retained earnings
Section 179
Form 4562 reference status
Strategies include:

S-Corp Reasonable Compensation Planning
Retirement Plan Design
Defined Benefit / Cash Balance Plan
Accountable Plan
Dental Equipment Depreciation Planning
QBI Deduction Optimization
Form 1040
Status:

working with cross-check and review workflow
Supports:

simple 1040 extraction
complex 1040 package detection
text vs vision cross-check
safe questionnaire merge
reviewed-field approval
Important behavior:

Complex PDFs may produce conflicting text and vision values.
The system does not trust conflicts.
Form 1065
Status:

working for current test package
Extracted values include:

total assets
number of K-1s
gross receipts
COGS
gross profit
total income
total deductions
ordinary business income
Strategies include:

QBI Deduction Optimization
Entity Structure Review
Retirement Plan Design
Tax Planning Fee Deduction
Form 1120
Status:

pending
Needs:

detection test with real 1120 PDF
extraction card
questionnaire mappings
deterministic rules
AI strategy policy refinements
8. Environment Variables
Create .env in the project root.

Example:

OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
OPENAI_VISION_MODEL=gpt-4o-mini
Optional OpenRouter configuration:

OPENROUTER_API_KEY=your_key_here
OPENROUTER_API_URL=https://openrouter.ai/api/v1/chat/completions
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_VISION_MODEL=openai/gpt-4o-mini
Do not commit .env.

9. Installation
Create virtual environment and install dependencies:

pip install -r requirements.txt
Run app:

python main.py
Open:

http://127.0.0.1:8000
API docs:

http://127.0.0.1:8000/docs
10. Git Ignore
Make sure .gitignore includes:

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
11. Current Development Status
Completed:

PDF text extraction
PDF image rendering
Form detection
1120-S extraction/report flow
1040 extraction/cross-check/review flow
1065 extraction/report flow
Questionnaire merge
Strategy rules
AI strategy matcher
Final report generator
Frontend index.html
In progress / next:

1120 C-corp support
Review UI for conflicted fields
Better schedule-specific extraction cards
Google Document AI integration
Persistent database
S3 file storage
User accounts
Strategy knowledge base / Pinecone
12. Next Developer Tasks
Recommended order:

Add Form 1120 C-Corp support
Add UI for reviewing conflicting fields
Store uploaded PDFs and extraction results in database
Add S3 storage
Add Google Document AI OCR/layout extraction
Add schedule-specific extraction cards:
Schedule A
Schedule B
Schedule D
Schedule E
K-1
Form 4562
Add Pinecone strategy knowledge base
Build proper React/Next.js frontend
Add authentication and client records
13. Key Product Rule
This is the most important rule in the whole project:

If the system is not sure, it must not guess.
It must ask the user to review.
This is what makes the system CPA-safe.

14. Summary
TaxTruth is becoming a CPA-review tax strategy engine.

The system can already:

read PDFs
detect tax forms
extract tax facts
cross-check text and vision
fill questionnaires safely
run deterministic tax strategy rules
use AI to match approved strategies
generate final reports
The end goal is a production platform where users upload tax returns and receive clear, reviewed, CPA-style strategy recommendations with full transparency and no hidden guessing.