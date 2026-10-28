<!--
Booth one-pager, Course Access Agent. "Course Access Agent" and "campus-ai" are
working names: decision D4 in docs/plans/master_plan.md says Teamworx branding
is still to be decided. Replace the name, the contact line and the logo before
printing. Numbers come from evals/course_access/ (reports dated 2026-10-22 and
2026-10-23); update them if a newer report is committed.
-->

# Course Access Agent

**Accessible course materials, built on your own machines.**

## The problem

Lecture slides, PDFs and Word files are often not accessible: images with no
description, slides with no titles, tables a screen reader cannot follow.
Students find out when they cannot use the material, and the accessibility
office then fixes it one document and one accommodation request at a time.

## Why now

- **Accessible British Columbia Act:** post-secondary institutions are now
  covered, so inaccessible course material is an institutional duty, not a
  favour.
- **EU Web Accessibility Directive and EN 301 549:** the same expectations
  for institutions that work in or with Europe.
- **WCAG 2.2 AA** is the standard all three point to.

## What it does

1. **Drop in a course document** (PDF, PowerPoint or Word).
2. **Audit:** fixed rules check it against WCAG 2.2 AA and say where each
   problem is.
3. **Propose:** small workers suggest a fix for each problem (real headings
   and lists, slide titles, table headers, link text, document language,
   image descriptions). Every proposal shows its **confidence and its
   evidence**.
4. **You decide:** approve, edit or reject each one. Charts, diagrams,
   equations and anything the system is unsure about always wait for a person.
5. **Rebuild and check:** you get an accessible DOCX and HTML version, a
   report mapped to WCAG, and a short conformance statement. The rebuilt file
   is audited again with the same checker, so the before and after numbers
   are comparable.

It never changes the academic content: only structure and descriptions.

## What makes it different

- **Open source, Apache-2.0.** No paid licences anywhere in the stack.
- **Runs offline.** Every model, including the one that looks at images, is
  an open-weight model running on your own machine. Nothing is sent to a
  cloud AI service, so course materials stay on your own machines, in your
  own region.
- **Checkable, not just clever.** Rules find and re-check problems; the
  model is used only for judgement, such as describing a picture.
- **A person approves** anything that carries meaning. Nothing is published
  automatically.

## Results so far

Measured on 20 openly licensed course documents (CC BY and CC BY-SA PDFs,
Word files and slide decks from Canadian and UK open-education repositories):

| | |
|---|---|
| Accessibility issues found by the audit | **862** |
| Remaining after applying only the fixes that need no review | **360** (58% fewer) |
| Issues introduced by the rebuild | 2 (both in one PDF) |
| Proposals waiting for a person | 51 |

The remaining 360 are mostly images that still need a description, which this
run deliberately left to the review step. These are counts from the rules, not
yet checked against an accessibility specialist's labels, and the image
descriptions come from a small model running on a laptop. We are saying
"in progress", not "done".

## Status and next

Working end to end today on a laptop: audit, proposals, review queue,
rebuild, statement. Next: equations, scanned pages (OCR), a specialist-labelled
test set, and a bake-off to choose the best image-description model.

## Contact

[Name, role, email, phone: to be filled in before printing]
