/* Small, safe Markdown renderer for Corvis's replies. Everything is HTML-escaped first,
   so nothing the model writes can inject scripts into the page. Works offline. */
(function () {
  "use strict";

  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function inline(text) {
    // Pull out code spans first so their contents aren't formatted.
    const codes = [];
    let s = esc(text).replace(/`([^`\n]+)`/g, (_, c) => {
      codes.push(c);
      return "\u0000" + (codes.length - 1) + "\u0000";
    });
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      (_, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`);
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>");
    s = s.replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
    s = s.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
  }

  function codeBlock(lang, code) {
    const label = lang ? esc(lang) : "code";
    return `<div class="code"><div class="code-head"><span>${label}</span>` +
           `<button type="button" data-copy>Copy</button></div>` +
           `<pre><code>${esc(code.replace(/\n$/, ""))}</code></pre></div>`;
  }

  function isTableSep(line) {
    return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
  }

  function splitRow(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  }

  function blocks(text) {
    const lines = text.split("\n");
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }

      let m;
      if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
        const n = m[1].length;
        out.push(`<h${n}>${inline(m[2])}</h${n}>`);
        i++; continue;
      }
      if (/^\s*(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/.test(line)) { out.push("<hr>"); i++; continue; }

      if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        const head = splitRow(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
          rows.push(splitRow(lines[i])); i++;
        }
        out.push("<table><thead><tr>" + head.map((h) => `<th>${inline(h)}</th>`).join("") +
                 "</tr></thead><tbody>" +
                 rows.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") +
                 "</tbody></table>");
        continue;
      }

      if (/^\s*>/.test(line)) {
        const quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) { quote.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
        out.push(`<blockquote>${blocks(quote.join("\n"))}</blockquote>`);
        continue;
      }

      const listRe = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
      if ((m = line.match(listRe))) {
        const ordered = /\d/.test(m[2]);
        const items = [];
        while (i < lines.length) {
          const lm = lines[i].match(listRe);
          if (lm && /\d/.test(lm[2]) === ordered) { items.push(lm[3]); i++; continue; }
          if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) {
            items[items.length - 1] += " " + lines[i].trim(); i++; continue;
          }
          break;
        }
        const tag = ordered ? "ol" : "ul";
        const task = (t) => t.replace(/^\[( |x|X)\]\s+/, (_, c) => (c === " " ? "☐ " : "☑ "));
        out.push(`<${tag}>` + items.map((t) => `<li>${inline(task(t))}</li>`).join("") + `</${tag}>`);
        continue;
      }

      const para = [];
      while (i < lines.length && lines[i].trim() &&
             !/^(#{1,4}\s|\s*>|\s*([-*+]|\d+[.)])\s)/.test(lines[i]) &&
             !(lines[i].includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1]))) {
        para.push(lines[i]); i++;
      }
      if (para.length) out.push(`<p>${para.map(inline).join("<br>")}</p>`);
      else i++;
    }
    return out.join("");
  }

  function render(md) {
    const parts = [];
    const fence = /```([\w+#.-]*)[^\n]*\n([\s\S]*?)(?:```|$)/g;
    let last = 0, m;
    while ((m = fence.exec(md))) {
      parts.push(blocks(md.slice(last, m.index)));
      parts.push(codeBlock(m[1], m[2]));
      last = fence.lastIndex;
    }
    parts.push(blocks(md.slice(last)));
    return parts.join("");
  }

  window.CorvisMarkdown = { render, escape: esc };
})();
