<!--
Booth one-pager, Research Assistant. "Research Assistant" and "campus-ai" are
working names: decision D4 in docs/plans/master_plan.md says Teamworx branding
is still to be decided. Replace the name, the contact line and the logo before
printing. Numbers come from evals/research_assistant/ (reports dated
2026-10-23); update them if a newer report is committed.
-->

# Research Assistant

**Find the right expert, the right Horizon Europe call and the right EU
partners, with the evidence on the page.**

## The problem

Canadian researchers can now take part in Horizon Europe's Pillar II, but
finding the right call and the right partners across Europe is slow and
depends on who you already know. Research offices do it by hand, call by call.
Industry, students and journalists who want the right expert at a university
face the same wall from the other side.

## Why now

- **Canada's association to Horizon Europe Pillar II** opens the biggest
  clusters (health, climate, digital, food and environment) to Canadian
  teams, under consortium rules that must be met before a proposal is valid.

## What it does

- **Experts:** ask in plain language ("who at SFU works on wildfire smoke and
  health?") and get researchers ranked by fit, each with the topics and
  publications behind the match.
- **Horizon calls:** describe a lab's work and see the open and forthcoming
  calls that fit, with deadlines and a link to the official portal page.
- **EU partners:** for a call, get a ranked shortlist of European
  organisations, each with the Horizon projects that are the evidence
  (coordinators count more).
- **Consortium check and draft:** the Horizon consortium rule is checked by
  fixed rules, and the local model drafts a short brief for the research
  office. Any sentence that cites something outside the evidence is dropped
  before you see it.
- **Collections search:** one question over heritage collections, by words,
  meaning, or by dropping in a picture. Today: a pilot on Europeana's open
  salmon collection.

## What makes it different

- **Open source, Apache-2.0.** No paid licences anywhere in the stack.
- **Runs offline.** Every model (search, language, vision) is an open-weight
  model on your own machine. Nothing goes to a cloud AI service, and data
  stays in your region.
- **Every result cites its evidence:** a publication, a project or a call
  identifier you can click.
- **Ranked by fit to the work, never by personal attributes.** Public
  scholarly data only.
- **A person approves.** It drafts; the research office decides. Nothing is
  sent or published automatically.

## Results so far

- **Partner back-test:** we took 200 past Horizon Europe projects that had a
  Canadian partner, hid one European partner, and asked the system to find it.
  It was in the **top 10 for 63 of 200 (recall@10 = 0.32)**. That is a first
  baseline from a small model on a laptop; we have not yet tried the
  improvements we have planned.
- **Experts:** judged by reading the results. For the questions we tried
  (wildfire smoke and health, salmon and climate, medical imaging with machine
  learning, housing policy) the top results are plausible experts with the
  publications to show for it. This is not yet a scored measure.
- **Data in the demo:** 3,000 recent, highly cited SFU works (2,226 researchers,
  from OpenAlex), and the full Horizon Europe record from CORDIS (about 24,000
  projects, 36,000 organisations) plus 3,808 call topics.

## What is not connected yet

- **SFU's Research Expertise Engine (REE):** waiting on an agreement with SFU
  Research Intelligence. Public OpenAlex data for SFU authors stands in.
- **ArcaBC (BC collections):** pending permission from BC ELN. No data from it
  is used.

## Status and next

Working end to end on a laptop. Next: test the improvements on the same
back-test, analyse each call's full text, and connect REE and ArcaBC once the
agreements are in place.

## Contact

[Name, role, email, phone: to be filled in before printing]
