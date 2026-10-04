# Hook library

Raw material for the frame-0 hook card and the caption's first line. These are general patterns. If the owner keeps a record of which hooks have actually worked on their account, read it first and trust it over anything here, because a measured result on one audience beats a general rule.

---

## Pattern-interrupt openers

These work by opening a loop the viewer wants closed. They are openers, not whole hooks. Each one still needs the specific claim attached, or it is bait with nothing behind it.

1. nobody mentions this
2. i wish i knew this earlier
3. pause for a second
4. ever notice this pattern
5. here's the real truth
6. let me save you hours
7. this may surprise you
8. you need this now
9. you may not agree with this
10. i just figured this out

**Using them well:** the opener is the kicker, and the specific claim is the line under it. "I wish I knew this earlier" on its own gets scrolled past. "I WISH I KNEW THIS EARLIER" over "3 jobs ran before I woke up" is a hook.

**Using them badly:** stacking two openers, or attaching one to a vague claim. If the line under the kicker could headline any video on the account, rewrite it.

---

## What makes a frame-0 card stop a scroll

- **Specific beats clever.** "A client report. A blog post. Tomorrow's content." outperforms "Three things ran overnight." The concrete list is the payoff, so do not withhold it.
- **Numbers stop thumbs.** A digit in the first frame reads faster than a word. "3 jobs. 0 prompts." parses before the eye reaches the second line.
- **Put the viewer at stake.** A hook that opens with something happening to the viewer, or something they stand to lose, tends to hold better than one that opens with neutral information about an industry or a product.
- **An offer naming a specific thing works.** "Comment SCRIPT and I'll send you the script" names an artifact the viewer can picture getting. It is a legitimate hook, not only a call to action.
- **Never restate the voiceover.** If the card says what the speaker is about to say in the next three seconds, it has added nothing. Sharpen it or add to it.
- **Avoid opening on a negation.** "None of it is a chatbot" defines a thing by what it is not, and assumes the viewer already holds the frame being negated.
- **Legible at thumb size.** Two lines at most, kicker plus claim. Check it shrunk to 360px wide.
- **No runway.** No establishing shot, no wipe into the good bit, no card that resolves into the hook a second later. The hook is the first thing on screen, which is why the `hook` card is fully opaque on frame 0.
- **The first three seconds are a separate problem from frame 1.** Stopping the scroll gets you the frame. Holding needs a reason to stay: an open loop, a promised list with a count, or a claim the viewer wants to argue with.

**The test:** look at frame 0 on its own. If a stranger seeing only that image would not stop, there is no hook, whatever happens at second three.

---

## One line, three placements

Write the hook once and use the same words on the frame-0 card, the Instagram cover and the YouTube thumbnail, so the package reads as one thing and the cover matches what the video opens on.

---

## Scored by its own reviewer

The `visual_hook` dimension is graded by a reviewer that looks at the frame-0 picture (`preview-0s.png` from `reel-preview.py`) rather than the JSON. It gates at 90 like every other dimension. See Phase 6 in SKILL.md.
