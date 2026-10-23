---
title: R
summary: Language for statistics, data analysis and charts, widely used in science and research.
tags: [language, data, statistics, science, charts]
---
# R

## Overview
R is built for working with data: loading tables, statistics, and publication-quality charts (ggplot2). The "tidyverse" packages make data cleaning readable. Python can do similar work; R is especially strong in statistics and academic research.

## Setup and running
- Install R from cran.r-project.org and RStudio (Posit) as the editor.
- Run a script: `Rscript analysis.R`. Install packages: `install.packages("tidyverse")`.

## Core syntax
```r
name <- "Tony"                 # <- assigns
power <- 100
readings <- c(42, 17, 88)      # vector
mean(readings); max(readings)
readings[readings < 50]        # filtering; indexes start at 1

suits <- data.frame(
  mark = c(42, 43, 2),
  power = c(90, 40, 75)
)
suits[suits$power > 50, ]      # rows where power > 50

square <- function(x) x^2
sapply(1:5, square)
```

## Tidyverse and charts
```r
library(dplyr)
library(ggplot2)

suits |>
  filter(power > 30) |>
  arrange(desc(power)) |>
  mutate(status = if_else(power > 60, "ready", "charging"))

ggplot(suits, aes(x = factor(mark), y = power)) + geom_col() + labs(x = "Mark", y = "Power %")
```

## Common mistakes
- Forgetting R is 1-indexed.
- Using loops where vectorized functions are simpler and faster.
- Factors (categories) behaving unexpectedly when you expected text.
- Not handling missing values: use `na.rm = TRUE` in `mean()`, `sum()`.

## Learning path
### Level 1 — Basics
Vectors, data types, functions, data frames, reading CSV files.
Exercise: load a CSV of temperatures and compute the monthly average.

### Level 2 — Tidy data
dplyr verbs (filter, select, mutate, group_by, summarise), joins, tidyr reshaping.
Exercise: analyze a public dataset and answer three questions.

### Level 3 — Visualization and statistics
ggplot2, distributions, t-tests, linear regression, R Markdown/Quarto reports.
Exercise: a report with charts and a regression on the dataset.

### Level 4 — Applied
Shiny web dashboards, machine learning (tidymodels), packages.
Exercise: an interactive Shiny dashboard for your data.
