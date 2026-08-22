# FAQ

### Can it write to my product?

No. Not as a default you can switch off: there is no flag that disables it. The
crawl runs behind a network guard that aborts every non read request in the
browser, so a misdirected click on Save never reaches your server. Sign in is
the one permitted write, and every one is recorded. See
[The read only guarantee](The-read-only-guarantee).

### Do I have to use a model?

No. Without one you still get the crawl, the drift queue, the rules, the
masking, the editions, the themes and all three output formats. What you lose is
the writing, the picture checks and selector healing.

### Which models work?

Verba speaks the Anthropic Messages API. Claude works directly. Through a
gateway that translates, other providers work too: on one real deployment the
picker offered twelve models including GPT variants, and they answer. The
gateway is asked what it carries rather than guessed at. See
[The writer](The-writer).

### Does my content get uploaded?

Only what a task needs: the section text, its crawl evidence, and for the
picture checks the image. Never the whole project. If you use the Claude Code
route, nothing leaves the machine's existing session.

### Will it invent things?

It is specifically built not to. A capture proves a control exists; it does not
prove what the control means. The writer is instructed to leave `TODO: describe
this.` rather than guess, and that marker fails the build so it can never ship.
Confident, fluent and wrong is the worst failure a documentation tool has.

What the product actually *is* comes from you, once, in `content/system.md`.

### Can I point it at production?

Yes, and `mask_required: true` on that connection refuses an unmasked crawl. The
safest arrangement is to document staging where the data is already fictional.
When staging is not representative, capture production with masking on and let
the picture checks read every image against the names that must never appear.

### What happens when the product changes?

That is the normal case, not the failure case. Drift compares what the crawl
read with what your sections claim. Renames are detected as renames rather than
a deletion plus an addition. Mechanical changes apply themselves; judgement
comes back to you.

### What happens when a selector breaks?

`verba capture --heal` proposes a replacement, and verifies it in the live page
before believing it. A selector that matches nothing is never proposed. See
[Healing selectors](Healing-selectors).

### Can I run it on a schedule?

Yes:

```bash
verba capture && verba fix && verba build --pdf
```

Nothing writes to your product, every change is in History with a diff and a
restore, and the build fails rather than shipping a marker.

### Can two people use it at once?

Yes. Every write takes an advisory lock and lands atomically. Tested with four
concurrent writers making eight hundred changes.

### Word or PDF?

Both, from one content tree, plus an HTML preview. `verba build --pdf`. The
sheet and margins are one setting, so the two cannot disagree about what they
are printed on.

### Can I edit the DOCX afterwards?

You can, and you will lose it on the next build. The document is structured
content plus a pipeline. Edit `content/sections/*.md`.

### How do I ship a customer branded version?

An edition. One content tree, several documents, and the neutral edition is
automatically held to not naming the customers your other editions name. See
[Editions](Editions).

### Can I use my own writing rules?

Yes. `content/house.md` replaces the built in set entirely. The built in rules
are one house's, and a tool that documents anybody's product cannot also insist
on one company's punctuation.

### Does it work on a product behind SSO with a second factor?

Yes. `auth: sso`, then `verba env signin <id>`: a real browser opens, you
complete whatever your identity provider asks, and the session is kept. No
password is stored anywhere.

### Does it need a GitHub repository, a database, or a server?

None of them. It is a Python package and a directory of files.

### What is the demo?

A small fictional admin console called Meridian, and a document built from it,
both in this repository. Every screenshot in the README and this wiki came from
it. Nothing points at anyone's real system.

### Why is it called Verba?

Words. The document is the words; everything else here exists to keep them true.
