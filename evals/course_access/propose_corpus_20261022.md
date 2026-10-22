# Worker proposals on the A6 corpus

2026-10-22 20:54 UTC. 20 documents, 533 proposals, 51 to review, 94 from the model (gemma4:e2b). Counts are what the rules produce; nothing is checked against labels yet.

| Action | Meaning | Proposals | To review | From the model |
|---|---|---|---|---|
| treat-as-layout | the table is layout, not data: read its text as paragraphs | 323 | 0 | 0 |
| set-link-text | replace the link text | 104 | 0 | 92 |
| promote-to-heading | make the paragraph a heading | 30 | 30 | 0 |
| convert-to-list | make the paragraph a real list item | 20 | 0 | 0 |
| retitle-slide | number a repeated slide title | 19 | 0 | 0 |
| add-slide-title | give the slide a title | 17 | 17 | 0 |
| mark-header-row | mark the first row as the header row | 9 | 2 | 0 |
| set-title | set the document title | 9 | 2 | 0 |
| set-language | set the document language | 2 | 0 | 2 |

| Document | Proposals | To review | From the model | Seconds |
|---|---|---|---|---|
| ecampusontario-oer101/oer-101-module-1.pdf | 47 | 10 | 10 | 174.9 |
| olds-profcomm-m1/foundations-etextbook.pdf | 213 | 3 | 42 | 646.8 |
| olds-profcomm-m1/foundations-lecture-notes.docx | 3 | 0 | 2 | 29.8 |
| olds-profcomm-m1/foundations-slides-Audience Slide Deck.pptx | 6 | 4 | 0 | 0.1 |
| olds-profcomm-m1/foundations-slides-Channels Slide Deck.pptx | 2 | 2 | 0 | 0.1 |
| olds-profcomm-m1/foundations-slides-Feedback Slide Deck.pptx | 4 | 4 | 0 | 0.1 |
| olds-profcomm-m1/foundations-slides-Introduction Slide Deck.pptx | 2 | 2 | 0 | 0.0 |
| olds-profcomm-m1/foundations-slides-Plain Language Slide Deck.pptx | 3 | 3 | 0 | 0.1 |
| olds-profcomm-m1/foundations-slides-Visuals Slide Deck.pptx | 2 | 2 | 0 | 0.0 |
| olds-profcomm-m3/presentations-etextbook.pdf | 199 | 21 | 34 | 547.9 |
| olds-profcomm-m3/presentations-lecture-notes.docx | 11 | 0 | 2 | 32.4 |
| olds-profcomm-m3/presentations-slides-Communicating with a Live Audience Slide Deck.pptx | 0 | 0 | 0 | 0.1 |
| olds-profcomm-m3/presentations-slides-Presentation Aids Slide Deck.pptx | 0 | 0 | 0 | 0.1 |
| olds-profcomm-m3/presentations-slides-Presentation Strategy Slide Deck.pptx | 0 | 0 | 0 | 0.1 |
| olds-profcomm-m3/presentations-slides-Your Presentation Style Slide Deck.pptx | 10 | 0 | 0 | 0.1 |
| ontariotech-edst3440u/course-outline.docx | 7 | 0 | 4 | 51.6 |
| ontariotech-edst3440u/week-02-slides.pptx | 2 | 0 | 0 | 0.1 |
| ontariotech-edst3440u/week-10-slides.pptx | 4 | 0 | 0 | 0.1 |
| ontariotech-edst3440u/week-12-slides.pptx | 6 | 0 | 0 | 0.1 |
| ucl-open-education/introduction-to-open-education.pptx | 12 | 0 | 0 | 0.0 |

## Samples to read

**set-language**

- oer-101-module-1.pdf: en (confidence 1.00)
- foundations-etextbook.pdf: en (confidence 1.00)

**promote-to-heading**

- oer-101-module-1.pdf: {"level": 1} (confidence 0.50, review: confidence 0.50 is below 0.7)
- oer-101-module-1.pdf: {"level": 1} (confidence 0.50, review: confidence 0.50 is below 0.7)
- oer-101-module-1.pdf: {"level": 1} (confidence 0.50, review: confidence 0.50 is below 0.7)

**treat-as-layout**

- oer-101-module-1.pdf: true (confidence 0.75)
- oer-101-module-1.pdf: true (confidence 0.75)
- oer-101-module-1.pdf: true (confidence 0.75)

**convert-to-list**

- oer-101-module-1.pdf: {"text": "Unsure", "ordered": true, "level": 1} (confidence 0.90)
- foundations-slides-Audience Slide Deck.pptx: {"text": "Inform", "ordered": true, "level": 1} (confidence 0.90)
- foundations-slides-Audience Slide Deck.pptx: {"text": "Entertain", "ordered": true, "level": 1} (confidence 0.90)

**mark-header-row**

- oer-101-module-1.pdf: true (confidence 0.85)
- foundations-etextbook.pdf: true (confidence 0.50, review: the first row may not be column headings; confidence 0.50 is below 0.7)
- foundations-etextbook.pdf: true (confidence 0.50, review: the first row may not be column headings; confidence 0.50 is below 0.7)

**set-link-text**

- oer-101-module-1.pdf: Watch video clip for Module 1 OER 101 (confidence 0.90)
- oer-101-module-1.pdf: Watch this video clip (confidence 1.00)
- oer-101-module-1.pdf: Undergraduate tuition fees information from York University (confidence 0.90)

**set-title**

- foundations-etextbook.pdf: null (confidence 0.00, review: no value could be derived; a person must supply one)
- foundations-lecture-notes.docx: How to Use this Document (confidence 0.85)
- presentations-etextbook.pdf: Creative Commons Attribution 4.0 License (confidence 0.50, review: no heading to take a title from; confidence 0.50 is below 0.7)

**add-slide-title**

- foundations-slides-Audience Slide Deck.pptx: Welcome! (confidence 0.60, review: a person should confirm it names the slide's subject; confidence 0.60 is below 0.7)
- foundations-slides-Audience Slide Deck.pptx: Audience Scenarios (confidence 0.60, review: a person should confirm it names the slide's subject; confidence 0.60 is below 0.7)
- foundations-slides-Audience Slide Deck.pptx: Write Your Own Message (confidence 0.60, review: a person should confirm it names the slide's subject; confidence 0.60 is below 0.7)

**retitle-slide**

- presentations-slides-Your Presentation Style Slide Deck.pptx: Active Listening (1 of 2) (confidence 0.90)
- presentations-slides-Your Presentation Style Slide Deck.pptx: Active Listening (2 of 2) (confidence 0.90)
- week-10-slides.pptx: Evaluation and Continuous Improvement (1 of 2) (confidence 0.90)
