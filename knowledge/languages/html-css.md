---
title: HTML & CSS
summary: The structure (HTML) and style (CSS) of every web page; the starting point for websites and web app design.
tags: [language, web, frontend, design, beginner, ui]
---
# HTML & CSS

## Overview
HTML describes what's on a page (headings, paragraphs, images, buttons). CSS describes how it looks (colors, spacing, layout). JavaScript adds behavior. All three run in any browser with no setup.

## Setup and running
Create `index.html`, open it in a browser. A code editor like VS Code with the "Live Server" extension reloads the page as you save.

## A complete page
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stark Industries</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header><h1>Stark Industries</h1></header>
  <main>
    <section class="card">
      <h2>Mark 42</h2>
      <p>Status: <strong>ready</strong></p>
      <img src="suit.png" alt="Red and gold armor suit">
      <button id="launch">Launch</button>
    </section>
  </main>
</body>
</html>
```

## CSS basics
```css
:root { --accent: #00e5ff; }          /* variable */
body { font-family: system-ui, sans-serif; margin: 0; background: #0b0f14; color: #e6edf3; }
.card {                               /* .class  #id  element */
  padding: 16px;                      /* inside spacing */
  margin: 16px auto;                  /* outside spacing; auto centers */
  max-width: 480px;
  border: 1px solid #1f2a33;
  border-radius: 12px;
}
button { background: var(--accent); border: 0; padding: 8px 16px; border-radius: 8px; cursor: pointer; }
button:hover { filter: brightness(1.1); }
```

## Layout: Flexbox and Grid
```css
.row { display: flex; gap: 12px; align-items: center; justify-content: space-between; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; }
@media (max-width: 600px) {           /* phone screens */
  .row { flex-direction: column; }
}
```

## Common mistakes
- Forgetting the viewport `<meta>` tag, so the page looks tiny on phones.
- Using `<div>` for everything: use meaningful tags (`header`, `nav`, `main`, `button`) for accessibility and SEO.
- Missing `alt` text on images.
- Fighting layout with fixed pixel widths and `position: absolute`; use Flexbox/Grid and `max-width`.
- Low color contrast between text and background.

## Learning path
### Level 1 — Structure
Tags, headings, paragraphs, links, images, lists, forms; semantic HTML.
Exercise: a personal profile page with a photo, a short bio and links.

### Level 2 — Style
Selectors, the box model, colors, fonts, spacing, CSS variables, hover states.
Exercise: style the profile page with a consistent color palette and spacing scale.

### Level 3 — Layout and responsiveness
Flexbox, Grid, media queries, mobile-first design, accessible contrast and focus states.
Exercise: a responsive product page that looks right on a phone and a desktop.

### Level 4 — Design systems
Design tokens, components, dark mode, animation and transitions, a CSS framework (Tailwind) or a component library.
Exercise: a small landing page with a light/dark theme toggle (with JavaScript).
