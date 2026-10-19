import importlib.util
import math
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reel_cut", SCRIPTS / "reel-cut.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)


def block(start, end, text, onset=None):
    ws, n = text.split(), max(1, len(text.split()))
    step = (end - start) / n
    words = [{"w": w, "s": start + k * step, "e": start + (k + 1) * step} for k, w in enumerate(ws)]
    return {"start": start, "end": end, "onset": start if onset is None else onset, "words": words}


def plan(*specs):
    blocks = [block(*s) for s in specs]
    words = [w for b in blocks for w in b["words"]]
    return rc.decide(rc.attach_words([{k: b[k] for k in ("start", "end", "onset")} for b in blocks], words))


class DecideTests(unittest.TestCase):
    def test_retake_keeps_the_later_take(self):
        bl = plan((0.0, 2.5, "Canada just joined the AI arms race."),
                  (3.5, 6.0, "Canada has joined the AI arms race,"),
                  (6.3, 8.0, "and nobody noticed."))
        self.assertEqual([b["decision"] for b in bl], ["CUT", "KEEP", "KEEP"])
        self.assertIn("retake", bl[0]["reason"])

    def test_false_start_is_cut(self):
        bl = plan((0.0, 0.8, "and that"), (1.2, 4.0, "and that two hundred dollars bought nothing."))
        self.assertEqual(bl[0]["decision"], "CUT")

    def test_filler_with_silence_both_sides_is_cut(self):
        bl = plan((0.0, 2.0, "This is the first point."), (2.5, 2.8, "um"), (3.2, 5.0, "Here is the second."))
        self.assertEqual(bl[1]["decision"], "CUT")

    def test_filler_inside_a_phrase_is_flagged_not_cut(self):
        bl = plan((0.0, 3.0, "First, um, what it does is transcribe."), (3.5, 5.0, "Then it cuts."))
        self.assertEqual(bl[0]["decision"], "KEEP")
        self.assertTrue(any("filler" in f for f in bl[0]["flags"]))

    def test_stutter_flagged_but_emphasis_is_not(self):
        bl = plan((0.0, 2.0, "the the tool works"), (3.0, 5.0, "it is never never hands off"))
        self.assertTrue(any("stutter" in f for f in bl[0]["flags"]))
        self.assertFalse(bl[1]["flags"])

    def test_direction_to_camera_is_cut(self):
        bl = plan((0.0, 1.5, "okay let me redo that"), (2.0, 4.0, "Here is the real line."))
        self.assertEqual(bl[0]["decision"], "CUT")

    def test_different_lines_are_not_retakes(self):
        bl = plan((0.0, 2.0, "Open ChatGPT on your phone."),
                  (2.5, 4.5, "Then type the prompt below."),
                  (5.0, 7.0, "Copy the answer into notes."))
        self.assertTrue(all(b["decision"] == "KEEP" for b in bl))


    def test_off_camera_aside_is_cut(self):
        bl = plan((0.0, 3.0, "Here is the first point."), (5.0, 5.6, "Grab it."),
                  (7.0, 9.0, "And here is the second."))
        self.assertEqual(bl[1]["decision"], "CUT")
        self.assertIn("aside", bl[1]["reason"])

    def test_same_opening_run_is_a_retake(self):
        bl = plan((0.0, 3.0, "Don't forget to share this if you think it's useful."),
                  (3.5, 7.0, "Don't forget to share this if you know somebody using Claude."))
        self.assertEqual(bl[0]["decision"], "CUT")

    def test_cut_off_fragment_is_cut_but_full_sentence_before_it_is_flagged(self):
        bl = plan((0.0, 2.0, "That's about it to the des -"),
                  (2.5, 6.0, "That's about it for the app. If you -"),
                  (6.5, 9.0, "If you're looking for prompts, visit the vault."))
        self.assertEqual(bl[0]["decision"], "CUT")
        self.assertEqual(bl[1]["decision"], "KEEP")
        self.assertTrue(bl[1]["flags"])

    def test_split_sentences_at_a_dip(self):
        b = block(0.0, 4.0, "First line here. Second line now.")
        b.update(i=0, gap_after=None)
        env = ([k / 50 for k in range(200)], [-50.0 if 98 <= k <= 102 else -20.0 for k in range(200)])
        out = rc.split_sentences([b], env, -38)
        self.assertEqual([o["text"] for o in out], ["First line here.", "Second line now."])
        self.assertAlmostEqual(out[1]["onset"], 1.98, places=2)


    def test_repeat_across_pause_cuts_whole_abandoned_blocks(self):
        bl = plan((0.0, 0.3, "So,"), (0.8, 1.6, "Claude,"), (2.5, 2.8, "so"),
                  (3.0, 6.0, "Claude shipped a lot of stuff."))
        self.assertEqual([b["decision"] for b in bl], ["CUT", "CUT", "KEEP", "KEEP"])

    def test_emphatic_repeat_is_not_cut(self):
        bl = plan((0.0, 0.5, "never,"), (1.0, 3.0, "never hands off."))
        self.assertEqual(bl[0]["decision"], "KEEP")


    def test_similar_line_after_new_content_is_not_a_retake(self):
        bl = plan((0.0, 3.0, "You can open that follow-up work in a separate session with one click."),
                  (3.5, 7.0, "And if you use the slash BTW feature it jumps within the session."),
                  (7.5, 10.0, "Now it can open up in a separate session."))
        self.assertTrue(all(b["decision"] == "KEEP" for b in bl))


    def test_parallel_lines_are_not_false_starts(self):
        bl = plan((0.0, 0.6, "I love to"), (0.8, 1.6, "experiment."), (2.0, 4.0, "I love to try new things."))
        self.assertTrue(all(b["decision"] == "KEEP" for b in bl))

    def test_multi_block_retake_with_leading_connector(self):
        bl = plan((0.0, 0.8, "Read through them and"), (1.0, 1.8, "then try this"), (2.0, 2.4, "prompt."),
                  (3.0, 6.0, "So read through them and then try this prompt."))
        self.assertEqual([b["decision"] for b in bl], ["CUT", "CUT", "CUT", "KEEP"])


    def test_next_line_restarting_with_this_lines_words(self):
        bl = plan((0.0, 2.0, "Now it can open up in a separate session."),
                  (2.5, 6.0, "Open up in a separate tab so that it is its own session."))
        self.assertEqual([b["decision"] for b in bl], ["CUT", "KEEP"])


class ClipTests(unittest.TestCase):
    def test_in_on_onset_out_plus_frame_and_sentence_beat(self):
        bl = plan((1.0, 2.0, "Hello there.", 1.1), (3.0, 4.0, "Next line", 3.05))
        clips = rc.clips_from(bl, 30.0, 10.0)
        self.assertEqual(clips[0]["in_frame"], 33)                 # floor(1.1*30), no pad
        self.assertEqual(clips[0]["out_frame"], round((2.0 + rc.BEAT_SENTENCE) * 30) + 1)
        self.assertEqual(clips[1]["out_frame"], math.ceil((4.0 + rc.BEAT_WORD) * 30) + 1)  # word gap

    def test_beat_never_runs_into_next_onset(self):
        bl = plan((1.0, 2.0, "Short gap.", 1.0), (2.05, 3.0, "next", 2.05))
        clips = rc.clips_from(bl, 30.0, 10.0)
        self.assertEqual(len(clips), 1)                            # touching clips merge

    def test_cut_blocks_leave_no_gap(self):
        bl = plan((0.0, 2.5, "Canada just joined the AI arms race."),
                  (3.5, 6.0, "Canada has joined the AI arms race,"))
        clips = rc.clips_from(bl, 30.0, 10.0)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["blocks"], [1])


if __name__ == "__main__":
    unittest.main()
