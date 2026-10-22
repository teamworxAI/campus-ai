# Alt-text probe run: gemma4:e2b

2026-10-22 15:49 UTC. Kind right for 6/6; review routing right for 6/6 (images that must go to review did). Times include model loading on the first call.

| Probe | Expected kind | Got | Kind ok | Routing ok | Seconds |
|---|---|---|---|---|---|
| bar chart | chart | chart | yes | yes | 20.6 |
| flow diagram | diagram | diagram | yes | yes | 14.3 |
| equation | equation, text | equation | yes | yes | 15.3 |
| text slide | text | text | yes | yes | 19.8 |
| divider line | decorative | decorative | yes | yes | 15.7 |
| shapes | illustration, other, photo | illustration | yes | yes | 15.7 |

# Alt text proposals: probe deck

6 images need alt text; 5 need review, 1 can be applied as proposed. Nothing is changed until approved.

## Image at block 1 (page 1): chart, confidence 1.00

- **Alt:** A bar chart showing the variation in Sockeye returns across five years, highlighting significant fluctuations.
- **Long description:** This bar chart displays Sockeye returns (in millions) for the years 2018 through 2022. The returns were 1.2 million in 2018, increased to 1.8 million in 2019, dropped significantly to 0.9 million in 2020, reached the highest return of 2.4 million in 2021, and ended at 1.5 million in 2022.
- **Review:** charts always go to review
- **Model:** gemma4:e2b

## Image at block 1 (page 1): diagram, confidence 1.00

- **Alt:** A flow diagram illustrating the freshwater life cycle stages from egg to smolt.
- **Long description:** This diagram illustrates the sequential stages of the freshwater life cycle, showing the progression from the Egg stage, through the Fry stage, and culminating in the Smolt stage.
- **Review:** diagrams always go to review
- **Model:** gemma4:e2b

## Image at block 1 (page 1): equation, confidence 1.00

- **Alt:** The equation N(t) = NO * e^(rt) models the exponential growth of a population over time.
- **Long description:** This equation represents the formula for exponential growth of a population. N(t) is the population size at time t, NO is the initial population size, e is the base of the natural logarithm, r is the continuous growth rate, and t is the time. This formula describes a situation where the rate of population increase is proportional to the current population size.
- **Review:** equations always go to review
- **Model:** gemma4:e2b

## Image at block 1 (page 1): text, confidence 1.00

- **Alt:** This slide lists the required reading materials and homework assignment for the upcoming week.
- **Long description:** The slide, labeled as Slide 1 of the Probe deck, outlines the reading for the next week, which includes: Groot et al. (1995), chapter 3, and Quinn (2018), pages 40-62, along with a homework assignment.
- **Review:** images of text always go to review
- **Model:** gemma4:e2b

## Image at block 1 (page 1): decorative, confidence 1.00

- **Decorative:** no alt text; the image is hidden from screen readers.
- **Review:** marking an image decorative hides it from screen readers
- **Model:** gemma4:e2b

## Image at block 1 (page 1): illustration, confidence 1.00

- **Alt:** Two colored shapes, a red circle and a green square, are used as an example to illustrate color contrast.
- **Long description:** This illustration displays two distinct colored shapes: a large red circle on the left and a large green square on the right, serving as an example of color contrast for learning purposes.
- **Review:** not needed
- **Model:** gemma4:e2b
