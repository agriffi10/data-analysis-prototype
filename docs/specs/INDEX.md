# Spec Index

One row per spec. Files are `docs/specs/SPEC-<NN>-<slug>.md`; each file's header carries the
authoritative `Status`. Delivery write-ups (completed specs) are in `docs/spec-delivery/`.
Add a row when a spec is created; update its status on completion (status only — keep it terse).

| Spec | Status |
|---|---|
| 001 — S3 File Listing | Completed |
| 002 — Browse Prefixes (public bucket file browser) | Completed |
| 003 — Project IaC (OpenTofu) | Completed |
| 004 — GitHub Actions CI (test + build) | Completed |
| 005 — Deploy App to AWS (GitHub Actions + OpenTofu) | Completed |
| 006 — Cognito User Pool IaC (`auth` module) | Completed |
| 007 — Login Flow (Hosted UI + Amplify) | Completed |
| 008 — Auth-Gated Layout (react-router) | Completed |
| 009 — Sign-Up End to End | Completed |
| 010 — User-Space Bucket IaC (`data` module) | Completed |
| 011 — Scoped Credentials (Identity Pool ABAC + portal role) | Completed |
| 012 — Pre-Signup Username Validation (Lambda) | Completed |
| 013 — Prefix-Scoped S3 Access + Browser Switchover | Completed |
| 014 — User Prefix Marker (DO_NOT_DELETE.txt) | Completed |
| 015 — File Download + Data Foundation (TanStack Query) | Completed |
| 016 — File Upload (managed, auto-multipart + progress) + Create Folder | Completed |
| 017 — File Metadata Panel | Completed |
| 018 — Delete Files and Folders (recursive) | Completed |
| 019 — Move & Rename (files and folders) | Completed |
| 020 — Upload Queue (multi-file, concurrency, cancel) | Completed |
| 021 — Design Token Baseline (Tailwind v4 @theme) | Completed |
| 022 — Landing Page Visual Polish | Completed |
| 023 — App Shell Visual Polish (Header + Layouts) | Completed |
| 024 — File Browser Visual Polish | Completed |
| 025 — Upload Dropzone Visual Polish | Completed |
| 026 — Dialogs Visual Polish | Completed |
| 027 — Metadata Panel Visual Polish | Completed |
| 028 — Shared UI Primitives (Button, Input, Badge, Banner, BrandMark) | Completed |
| 029 — Landing Page Full Design | Completed |
| 030 — Cognito Bot Signup Protection (WAF + ASF) | Completed |
| 031 — Document Title Management | Completed |
| 032 — Analytics Foundation IaC (Athena workgroup + admin bucket + Lake Formation) | Completed |
| 033 — Per-User Glue Database Provisioning (post-confirmation Lambda + LF grant) | Completed |
| 034 — Query Engine Data Layer (Athena/Glue services + per-user history) | Completed |
| 035 — Tabbed Dashboard + Query Workspace UI (Monaco editor) | Completed |
| 036 — Query History Panel UI | Completed |
| 037 — File Browser Pagination (25/page, Load more) | Completed |
| 038 — Query Results Pagination (20 rows/page, Prev/Next) | Completed |
| 039 — Copy Files and Folders (recursive) | Completed |
| 040 — Query Editor Session Persistence + Clear Button | Completed |
| 041 — Multi-Tab Query Editor | Completed |
| 042 — Query History Pagination (7/page, Prev/Next) | Completed |
| 043 — Saved Queries + Global Workspace Bar | Completed |
| 044 — Schema Browser Table Options Menu | Completed |
| 045 — Automated Accessibility (axe) Test Suite | Completed |
| 046 — Refresh History Button | Completed |
| 047 — Workspace Database/Connection Selector | Completed |
| 048 — Create View from Query + Views in Schema Browser | Completed |
| 049 — Save Query Results to Workspace (replaces Download CSV) | Completed |
| 050 — Shared-Space Foundation Infrastructure (Bucket 2 + control plane) | Completed |
| 051 — Create Shared Connection | Completed |
| 052 — Shared Connections List, Selector Integration & Refresh | Completed |
| 053 — Shared-Space Member Management (Owner) | Completed |
| 054 — Leave & Delete a Shared Space | Completed |
| 055 — Shared-Space Query Results Routing & Save | Completed |
| 056 — Shared-Space Access Model & Request Contract (membership tags + portal slots + LF) | Completed |
| 057 — Shared Spaces in the File Browser | Completed |
| 058 — Notifications Foundation Infrastructure (Write Pipeline + IAM) | Completed |
| 059 — Notifications Data Layer (Read Service + Hook) | Completed |
| 060 — Notifications UI (Header Bell Link + Notifications Page) | Completed |
| 061 — Shared-Workspace Notification Producer | Completed |
| 062 — Decompose Shared-Space Control Plane into Single-Task Lambdas | Completed |
| 063 — Schema Rail: Collapsible Databases with Tables/Views Groups | Completed |
| 064 — Resizable Query-Result Columns | Completed |
| 065 — Schema-Aware Editor Autocomplete (Table & Column Names) | Completed |
| 066 — Table Builder: Foundation Infrastructure + polars Runtime | Completed |
| 067 — Table Builder: Request Contract, Enqueue & Validate-Authorize | Completed |
| 068 — Table Builder: Name Uniqueness + Source Inspection & Format Validation | Completed |
| 069 — Table Builder: Schema Inference & DDL Generation (polars) | Completed |
| 070 — Table Builder: Execute DDL & Terminal States | Completed |
| 071 — Table Builder: "Create Table from this Folder" (File Browser UI) | Completed |
| 072 — Table Builder: Notification Producer (per-step failure + success) | Completed |
| 073 — Shared-Space Member Join Status (Pending / Active) | Completed |
| 074 — Help & Guides Page (Top-Bar Icon + Documentation Page) | Completed |
| 075 — Shared-Space Member Roster for Members (read-only) | Completed |
| 076 — Per-Tab Query Database (+ Saved Query Targets Its Database) | Superseded (by SPEC-077) |
| 077 — Cross-Database Querying (drop the active-database session) | Completed |
| 078 — Multiple SQL Statements in One Editor | Completed |
| 079 — Editor / Results Layout Presets | Completed |
| 080 — Total Row Count in Query Stats | Completed |
| 081 — Double-Click a File to Download | Completed |
| 082 — Shared-Space Registry Write Concurrency (optimistic CAS) | Completed |
| 083 — Code-Quality Hardening (Lambda config/shape/types + Lambda & SPA cleanup smells) | Completed |
| 084 — Query Editor Autocomplete Lifecycle Fix (Monaco completion provider) | Completed |
| 085 — Collapsible Side Nav (shared base rail + collapse control) | Completed |
| 086 — Per-Database Schema Refresh (look for new tables/views) | Completed |
| 087 — Configurable Query-Results Page Size (default 100, user-adjustable, workspace-wide) | Completed |
| 088 — Table Share: Foundation Infrastructure + Common Layer | Completed |
| 089 — Table Share: Request Contract, Enqueue & Validate-Authorize | Completed |
| 090 — Table Share: Source Resolution & Copy Plan (inspect-source) | Completed |
| 091 — Table Share: Recipient Map + Copy (check-target-absent + copy-objects) | Completed |
| 092 — Table Share: Recipient Table Creation & Terminal States (create-table) | Completed |
| 093 — Table Share: "Share table" UI (Query Schema Rail) | Completed |
| 094 — Table Share: Notification Producer (sender + recipients) | Completed |
| 095 — Responsive Foundation & App Shell | Completed |
| 096 — Files: Selection Toolbar → Copy/Move/Delete | Completed |
| 097 — Files: Object Details Panel Gains Download & Rename | Completed |
| 098 — Files: Parent-Folder (`..`) Row | Completed |
| 099 — Files Responsive Layout | Completed |
| 100 — Query Workspace Responsive | Completed |
| 101 — Connections Responsive | Completed |
| 102 — Notifications Responsive | Completed |
| 103 — Help & Guides Responsive | Completed |
| 104 — Landing / Sign-In Responsive | Completed |
| 105 — View Data: Full Table, Paginated (drop 10-row preview limit) | Completed |
| 106 — User-Facing Error Messaging (friendly, no AWS leaks) | Completed |
| 107 — Shared `control-plane-common` Lambda Layer | Completed |
| 108 — Data Quality: Foundation Infrastructure + Common Layer + Athena Workgroup | Completed |
| 109 — Data Quality: Request Contract, Enqueue & validate-authorize | Completed |
| 110 — Data Quality: Source Inspection | Completed |
| 111 — Data Quality: Temp Tables + the Athena Profile Query | Completed |
| 112 — Data Quality: byte-scan + Report Assembly | Completed |
| 113 — Data Quality: File-Browser UI + Report View | Completed |
| 114 — Data Quality: Notification Producer | Completed |
| 115 — File Converter: Foundation Infrastructure + Layers + Athena Workgroup | Cancelled |
| 116 — File Converter: Request Contract, Enqueue & validate-authorize | Cancelled |
| 117 — File Converter: Source Inspection + Schema Reconciliation | Cancelled |
| 118 — File Converter: The Athena UNLOAD Path | Cancelled |
| 119 — File Converter: finalize + Terminal States | Cancelled |
| 120 — File Converter: File-Browser UI | Cancelled |
| 121 — File Converter: Notification Producer | Cancelled |
| 122 — File Converter: Create Table From Converted Files (chain to Table Builder) | Cancelled |
| 123 — Data Quality: Runs Dashboard (`/data-quality` list + nav + runs index) | Completed |
| 124 — Data Quality: Start a Check from the Dashboard (space + folder/file target picker) | Completed |
| 125 — Fold `shared-space-common` onto the `cpcommon` layer | Completed |
| 126 — Control-Plane DLQ Drain → User Notification | Completed |
| 127 — Structured Logging Foundation (`log-foundry` → logs queue → admin bucket) | Completed |
| 128 — Structured Logging: Instrument the Data-Quality Control Plane (pilot) | Completed |
| 129 — Logs Queue → FIFO, and One Object Per Service-Day | Completed |
| 130 — Structured Logging: Narrative Primitives and Function Identity | Completed |
| 131 — Structured Logging: Narrate the Log Sweep | Completed |
| 132 — Structured Logging: Narrate the Data-Quality Control Plane | Completed |
| 133 — Structured Logging: Instrument the Control-Plane DLQ Drain | Completed |
| 134 — Structured Logging: Instrument the Shared-Space Control Plane | Completed |
| 135 — Structured Logging: Instrument the Table-Builder Control Plane | Completed |
| 136 — Structured Logging: Instrument the Table-Share Control Plane | Completed |
| 137 — Structured Logging: Instrument the Singleton Lambdas | Completed |
| 138 — Security Scanning (SAST, dependencies, secrets, IaC, OWASP ZAP) | Completed |
| 139 — IAM Policy Scanning (Checkov over the rendered plan JSON) | Completed |
| 140 — CloudFront Response Headers Policy (CSP, HSTS, framing, header strip) | Completed |
| 141 — Cache-Control for the SPA Shell and Hashed Assets | Completed |
| 142 — Ragged Rows Counted Per File, Not Against the Union | Completed |
| 143 — Refresh Table: Request Contract, Mode Branch & Table Eligibility | Completed |
| 144 — Refresh Table: Schema Diff & Apply | Completed |
| 145 — Refresh Table: Menu Item, Dialog & Notifications | Completed |
| 146 — Username Directory: Daily Builder Lambda & Published Index | Completed |
| 147 — Username Directory: Browser Data Layer & Typeahead Combobox | Completed |
| 148 — Username Typeahead in Add Members & Table Share | Completed |
| 149 — Refresh Table: In-Place Rebuild via `glue:UpdateTable` | Completed |
| 150 — Portal Guardrails: Typecheck Gate, Enqueue Re-entrancy & the Error-Code Contract | Completed |
| 151 — Control-Plane Correctness: Single-File Checks, Teardown Integrity & DDL Escaping | Completed |
| 152 — Control-Plane Failure Notification: Telling the User When No Verb Ran | Completed |
| 153 — Test & Gate Integrity: Closing the Guards That Pass by Coincidence | Completed |
| 154 — Frontend Journey Coverage: Testing the Wires Between Tested Halves | Completed |
| 155 — Browser Shared Primitives & Component Decomposition | Completed |
| 156 — Lambda Layer Consolidation: Folding the Deliberate Twins onto `cpcommon` | Completed |
| 157 — Serialize Concurrent Table Refresh | Completed |
| 158 — Shared-Space Suggestions from the Local Cache | Completed |
| 159 — `user_settings/` Recovery from an Unreadable Document | Completed |
| 160 — Table Share at Scale: Transfer Manifest & Distributed-Map Copy | Completed |
| 161 — Table Share at Scale: Raised Caps, Wide Definitions & Long Runs | Completed |
| 162 — Feature Flags: Document, Publish Pipeline & Browser Data Layer | Completed |
| 163 — Feature Flags: Gating Nav, Routes & Cross-Feature Entry Points | Completed |
| 164 — Send Files: Foundation Infrastructure & validate-authorize | Completed |
| 165 — Send Files: Source Resolution & Copy Plan | Completed |
| 166 — Send Files: Recipient Guard, Distributed-Map Transfer & Terminals | Completed |
| 167 — Send Files: "Send to…" UI & Notification Producer | Completed |
| 168 — Archive: Foundation Infrastructure, the Archive Bucket & validate-authorize | Completed |
| 169 — Archive: Source Resolution, Glacier Transfer & Source Deletion | Completed |
| 170 — Restore: Request Contract, Archive Lookup & the Destination Guard | Completed |
| 171 — Restore: Glacier Retrieval, the Wait Loop, Copy-Back & Terminals | Completed |
| 172 — Archive & Restore: File-Browser UI, the Receipt Surface & Notifications | Completed |
| 173 — Saved Queries as Files: the `saved_queries/` Folder, Its Protections & the Store | Completed |
| 174 — Saved Queries: Loading from a Chosen Space | Completed |
| 175 — Saved Queries: Saving into a Chosen Space | Completed |
| 176 — Extracting `features/catalog/` — the Shared Catalog & Execution Layer | Completed |
| 177 — Extracting `features/saved-queries/` — the Shared `.sql` Store | Completed |
| 178 — The Exploration Model, the SQL Renderer & the Execution Cache | Completed |
| 179 — Data Explorer: the Feature Flag, the `/explore` Route & the Shell | Completed |
| 180 — The Grid, Cell Selection, the Value Panel & the Record View | Completed |
| 181 — Filtering and Ordering | Completed |
| 182 — The Calc and Grouping Panels | Completed |
| 183 — Saving an Exploration as a Saved Query | Completed |
| 184 — Presentation and Formatting | Completed |
| 185 — Copy, Export, Help & the Arc's Live Checks | Completed |
| 186 — Live-Check Reachability, Refusal Affordances & Observability Fields | Draft |

## Arcs

Arc narrative (why an arc exists, how its specs compose) lives in `@docs/specs/ARCS.md` — pull it
only when you need the context for an arc you are working in.
