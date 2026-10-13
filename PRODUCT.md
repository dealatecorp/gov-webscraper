# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

TenderDesk is primarily for Indian SME owners and bid managers who regularly scan public procurement portals and need to decide quickly which opportunities are worth pursuing.

## Product Purpose

TenderDesk collects public government tender notices into one workspace so users can discover relevant opportunities, judge urgency, keep a personal watchlist, follow corrigenda, and return to official notices and documents for final verification. Success means reducing the time and uncertainty between discovering a notice and deciding whether to investigate or bid.

## Positioning

TenderDesk combines live public-notice collection with a user-specific opportunity workspace: one searchable archive, interest-based recommendations, deadline visibility, amendments, source health, watchlists, and saved public documents.

## Operating Context

Users work through a recurring procurement routine: review newly collected opportunities, scan relevance and deadlines, search by organisation or reference, shortlist promising notices, inspect changes, retrieve available tender PDFs, and verify eligibility and final dates on the official portal. Dates are presented in IST. The product is currently a localhost web application backed by SQLite, with a separate Vercel and Supabase deployment path in the repository.

## Capabilities and Constraints

- Preserve authentication, interest selection, recommendations, search, filtering, sorting, pagination, table and card views, watchlists, notice details, revision history, PDF retrieval, CSV export, collection controls, source health, collection history, and responsive behavior.
- Public portal coverage is limited and varies by source. TenderDesk must not imply complete coverage, eligibility, award status, or guaranteed real-time publication.
- Official portals remain the authority for final eligibility, documents, deadlines, and submission.
- CAPTCHA, authenticated portal flows, and inaccessible document endpoints are not bypassed.
- The local deployment is private and must not be presented as a production identity service.

## Brand Commitments

Keep the TenderDesk name and a direct, trustworthy, decision-oriented voice. Procurement language should be plain and operational rather than promotional.

## Evidence on Hand

- Live public notices collected from GeM, CPPP eProcurement, CPPP ePublishing, Defproc, and Hindustan Shipyard.
- Stored collection events, source-health states, deadlines, revisions, references, organisations, and user bookmarks.
- Existing frontend and workflow implementation under `web/`.
- No customer testimonials, completeness claims, bid-win claims, or performance benchmarks are available and none may be fabricated.

## Product Principles

1. Put the pursue-or-pass decision ahead of dashboard decoration.
2. Make urgency, relevance, provenance, and uncertainty visible at scan speed.
3. Keep users oriented from discovery through official verification.
4. Preserve trust by distinguishing collected facts from inferred guidance.
5. Make dense procurement information calm, comparable, and usable on desktop and mobile.

## Accessibility & Inclusion

The interface must support keyboard navigation, visible focus, semantic labels, reduced motion, legible contrast, and responsive use at mobile widths.
