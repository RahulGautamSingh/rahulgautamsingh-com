#!/opt/homebrew/bin/python3
"""Render an article's markdown into the site's HTML shell.

  ./build-article.py articles/renovate-clone-reduction.md

Supports what the articles actually use: headings, paragraphs, fenced code,
inline code, links, bold, italic, ordered and unordered lists, pipe tables,
and `[IMAGE: path | alt: text]` markers.
"""
import sys, os, re, html

# resume.html is deliberately unlisted: reachable by URL, not in the nav.
NAV = [("index.html", "About me"), ("articles.html", "Articles")]


def shell(title, desc, body, depth):
    up = "../" * depth
    nav = "\n".join(
        f'        <li><a href="{up}{href}"'
        f'{" aria-current=\"page\"" if href == "articles.html" else ""}>{label}</a></li>'
        for href, label in NAV)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} | Rahul Gautam Singh</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="stylesheet" href="{up}style.css">
<link rel="icon" href="data:,">
</head>
<body>
<div class="layout">

  <aside class="sidebar">
    <div class="brand">
      <a href="{up}index.html">Rahul Gautam Singh</a>
      <small>Full-Stack AI Engineer</small>
    </div>
    <nav>
      <ul>
{nav}
      </ul>
    </nav>
    <footer>Delhi, India<br>Open to remote, worldwide</footer>
  </aside>

  <main>
    <article>
{body}
      <p class="meta" style="margin-top:44px">
        <a href="{up}articles.html">&larr; All articles</a>
      </p>
    </article>
  </main>

</div>
</body>
</html>
"""


def inline(t, up):
    """Inline markup. Code spans are protected first so their contents stay literal."""
    spans = []
    def stash(m):
        spans.append(m.group(1))
        return f"\x00{len(spans)-1}\x00"
    t = re.sub(r"`([^`\n]+)`", stash, t)
    t = html.escape(t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{html.escape(spans[int(m.group(1))])}</code>", t)
    return t


def convert(md, up):
    out, i = [], 0
    lines = md.split("\n")
    img_re = re.compile(r"`?\[IMAGE:\s*([^|\]]+?)\s*\|\s*alt:\s*([^\]]+?)\s*\]`?")

    while i < len(lines):
        ln = lines[i]

        if ln.startswith("```"):                                   # fenced code
            lang, i, buf = ln[3:].strip(), i + 1, []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            out.append(f'<pre><code>{html.escape(chr(10).join(buf))}</code></pre>')
            continue

        m = img_re.fullmatch(ln.strip())                           # image marker
        if m:
            src, alt = m.group(1).strip(), m.group(2).strip()
            src = re.sub(r"^memes/", "", src)
            out.append(f'      <figure class="meme">\n'
                       f'        <img src="{up}images/{src}" alt="{html.escape(alt)}" loading="lazy">\n'
                       f'      </figure>')
            i += 1
            continue

        if ln.startswith("|"):                                     # table
            rows, i = [], i
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
            rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
            if rows:
                head = "".join(f"<th>{inline(c, up)}</th>" for c in rows[0])
                body = "".join("<tr>" + "".join(f"<td>{inline(c, up)}</td>" for c in r) + "</tr>"
                               for r in rows[1:])
                out.append(f"      <table>\n        <thead><tr>{head}</tr></thead>\n"
                           f"        <tbody>{body}</tbody>\n      </table>")
            continue

        m = re.match(r"^(#+)\s+(.*)", ln)                          # heading
        if m:
            lvl = min(len(m.group(1)), 3)
            out.append(f"      <h{lvl}>{inline(m.group(2), up)}</h{lvl}>")
            i += 1
            continue

        if re.match(r"^\d+\.\s", ln) or re.match(r"^[-*]\s", ln):  # list
            ordered = bool(re.match(r"^\d+\.\s", ln))
            items = []
            while i < len(lines) and (re.match(r"^\d+\.\s", lines[i]) or re.match(r"^[-*]\s", lines[i])):
                items.append(re.sub(r"^(\d+\.|[-*])\s+", "", lines[i])); i += 1
            tag = "ol" if ordered else "ul"
            lis = "\n".join(f"        <li>{inline(x, up)}</li>" for x in items)
            out.append(f"      <{tag}>\n{lis}\n      </{tag}>")
            continue

        if not ln.strip():                                         # blank
            i += 1
            continue

        para, = [[]]                                               # paragraph
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|```|\||\d+\.\s|[-*]\s)", lines[i]) \
                and not img_re.fullmatch(lines[i].strip()):
            para.append(lines[i]); i += 1
        txt = " ".join(para).strip()
        cls = ' class="meta"' if txt.startswith("Published ") else ""
        out.append(f"      <p{cls}>{inline(txt, up)}</p>")

    return "\n\n".join(out)


def main():
    src = sys.argv[1]
    md = open(src).read()
    depth = len(os.path.dirname(src).split(os.sep)) if os.path.dirname(src) else 0
    up = "../" * depth

    lines = md.split("\n")
    title = lines[0].lstrip("# ").strip()
    # first italic line is the standfirst; use it as the meta description
    m = re.search(r"^\*([^*]+)\*$", md, re.M)
    desc = m.group(1).strip() if m else title

    body = convert("\n".join(lines[1:]).strip(), up)
    body = f"      <h1>{html.escape(title)}</h1>\n\n" + body

    dst = os.path.splitext(src)[0] + ".html"
    open(dst, "w").write(shell(title, desc, body, depth))
    print(f"  {src}  ->  {dst}")
    print(f"  title: {title}")
    print(f"  desc:  {desc[:70]}")


if __name__ == "__main__":
    main()
