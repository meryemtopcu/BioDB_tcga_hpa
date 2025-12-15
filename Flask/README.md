# BioDB – Gene-Centric Integration of TCGA and Human Protein Atlas Data

BioDB is a lightweight Flask + MySQL web application designed to explore
gene-centric views by integrating RNA-seq expression data from TCGA with
gene-level protein summaries from the Human Protein Atlas (HPA).

The project focuses on **database modeling and data integration**, not on
advanced statistical analysis.

---

## Motivation

Public cancer datasets are structurally heterogeneous:

- **TCGA** provides RNA expression at the *sample level*
  (many rows per gene).
- **HPA** provides protein expression summaries at the *gene level*
  (one row per gene).

Although these datasets describe related biological processes, they are
not directly compatible.  
This project was built to:

- understand relational database design for biological data
- normalize heterogeneous datasets around a common entity (gene)
- practice backend-driven data exploration via a web interface

---

## Data Sources

### The Cancer Genome Atlas (TCGA)
- RNA-seq gene expression data
- One row per `(sample_id, gene)`
- Numeric expression values

### Human Protein Atlas (HPA)
- Gene-level protein detection summaries
- Categorical expression levels:
  `high`, `medium`, `low`, `not detected`

---

## Database Design

The database follows a **gene-centric relational model**.

### Core Tables

```text
tcga_expression
---------------
sample_id
gene_id (FK → genes.gene_id)
expression_values

hpa_summary
-----------
gene_id (FK → genes.gene_id)
high
medium
low
not_detected

---

## Design Rationale

- The `genes` table normalizes gene identifiers across all datasets.
- TCGA expression data is stored as a **one-to-many** relationship per gene,
  reflecting sample-level measurements.
- HPA data is stored **once per gene**, representing gene-level protein summaries.
- This structure enables joint querying of TCGA and HPA data using a
  single gene identifier while preserving their original granularity.

---

## Application Architecture

- **Backend:** Flask (Python)
- **Database:** MySQL
- **Frontend:** HTML + Bootstrap
- **Visualization:** Chart.js

---

## Data Flow

```text
User input (gene name)
→ Flask route
→ SQL queries
→ Data aggregation
→ HTML tables and charts

---

## Features

- Search by gene name
- TCGA per-sample expression table
- HPA gene-level protein summary
- External links to:
  - Human Protein Atlas gene pages
  - TCGA-related resources

---

## Requirements

### Backend
- Python 3.10+
- Flask
- MySQL or MariaDB

### Frontend
- Bootstrap 4+
- Modern web browser

---

## Author
Project design, database modeling, and backend development by:
<Meryem Topcu>
