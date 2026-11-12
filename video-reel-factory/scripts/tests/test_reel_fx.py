import importlib.util
import re
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import reel_cards as C
import reel_cards_panel as P
import reel_fx as FX

spec = importlib.util.spec_from_file_location("reel_compose", SCRIPTS / "reel-compose.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)

BANNED = ("tl.call(", "fromTo(", "Math.random", "Date.now", "backdrop-filter")


def title(**kw):
    return dict({"type": "title", "at": 2.0, "out": 5.0, "text": "Your AI team works **overnight**"}, **kw)


class TextMotionTests(unittest.TestCase):
    def test_every_motion_renders_in_every_look_and_obeys_the_render_contract(self):
        for motion in FX.TEXT_MOTIONS:
            for look in FX.TITLE_LOOKS:
                css, html, js = C.render_card(3, title(motion=motion, look=look))
                for bad in BANNED:
                    self.assertNotIn(bad, js + css, f"{motion}/{look} uses {bad}")
                self.assertIn("tl.", js)
                self.assertIn("ti3", html)

    def test_every_motion_starts_at_the_card_time_not_before(self):
        for motion in FX.TEXT_MOTIONS:
            _, _, js = C.render_card(0, title(motion=motion))
            times = [float(t) for t in re.findall(r"\},([\d.]+)\);", js)]
            moving = [t for t in times if t > 0]
            self.assertTrue(moving and min(moving) >= 2.0, motion)

    def test_every_exit_plays_at_out(self):
        for name in FX.TEXT_EXITS:
            _, _, js = C.render_card(0, title(exit=name))
            self.assertTrue(js.rstrip().endswith(",5.0);"), name)

    def test_text_is_escaped(self):
        _, html, _ = C.render_card(0, title(text="<script>x</script>", motion="typewriter"))
        self.assertNotIn("<script>", html)

    def test_unknown_names_are_refused_by_name(self):
        for field in ("motion", "exit", "look", "align"):
            with self.assertRaises(C.CardValueError) as e:
                C.render_card(0, title(**{field: "nope"}))
            self.assertIn(field, str(e.exception))

    def test_order_slots(self):
        self.assertEqual(FX._order(5, "start"), [0, 1, 2, 3, 4])
        self.assertEqual(FX._order(5, "centre"), [2, 1, 0, 1, 2])
        self.assertEqual(FX._order(5, "edges"), [0, 1, 2, 1, 0])


class CardTests(unittest.TestCase):
    def test_fx_cards_reach_every_style(self):
        for render in (C.render_card, P.render_card):
            for card in (title(), {"type": "checklist", "at": 1, "out": 4, "items": ["a", "b"]},
                         {"type": "cutaway", "at": 1, "out": 4, "src": "assets/a.jpg"}):
                css, html, js = render(1, card)
                self.assertTrue(html)

    def test_every_transition_pair(self):
        for t_in in FX.TRANSITIONS:
            for t_out in FX.TRANSITIONS:
                _, html, js = C.render_card(0, {"type": "cutaway", "at": 1, "out": 4, "in": t_in,
                                                "exit": t_out, "src": "assets/a.jpg"})
                for bad in BANNED:
                    self.assertNotIn(bad, js)

    def test_a_clip_becomes_a_timed_video_element(self):
        _, html, _ = C.render_card(2, {"type": "cutaway", "at": 1, "out": 4, "src": "assets/c.mp4"})
        self.assertIn("<video", html)
        self.assertIn('data-start="1"', html)
        self.assertIn('data-duration="3"', html)

    def test_cutaway_too_short_is_refused(self):
        with self.assertRaises(C.CardValueError):
            C.render_card(0, {"type": "cutaway", "at": 1, "out": 1.5, "src": "a.jpg"})

    def test_unknown_type_still_fails(self):
        with self.assertRaises(SystemExit):
            C.render_card(0, {"type": "nope", "at": 1, "out": 2})


class CaptionTests(unittest.TestCase):
    LINES = [{"start": 1.0, "end": 2.0, "words": [{"w": "the", "s": 1.0, "e": 1.2},
                                                 {"w": "desktop", "s": 1.2, "e": 1.7},
                                                 {"w": "app", "s": 1.7, "e": 2.0}]}]

    def test_keyword_picks_the_longest_word_or_the_marked_one(self):
        self.assertEqual(FX._keyword_index(self.LINES[0]["words"]), 1)
        marked = [dict(w) for w in self.LINES[0]["words"]]
        marked[2]["k"] = True
        self.assertEqual(FX._keyword_index(marked), 2)

    def test_both_modes_render(self):
        for fn in FX.CAPTION_FUNCS.values():
            css, html, js = fn(self.LINES)
            self.assertIn("desktop", html)
            for bad in BANNED:
                self.assertNotIn(bad, js)


class CompositeTests(unittest.TestCase):
    def test_no_effects_leaves_the_command_as_it_was(self):
        lines = rc.composite_command(None, 30, "", False, False)
        self.assertEqual(len(lines), 5)
        self.assertIn(f"fps=30,{rc.NORMALISE_V}[bg]", lines[1])
        self.assertNotIn("zoompan", "".join(lines))

    def test_grade_and_moves_go_on_the_footage_before_the_overlay(self):
        moves = FX.normalise_footage([{"move": "push-in", "at": 2, "out": 6}])
        lines = rc.composite_command(None, 30, "", grade="warm", footage=moves)
        self.assertIn("colorbalance", lines[1])
        self.assertIn("zoompan", lines[1])
        self.assertLess(lines[1].index("colorbalance"), lines[1].index("[bg]"))

    def test_music_adds_an_input_and_ducks(self):
        music = FX.normalise_music({"file": "bed.mp3"})
        text = "\n".join(rc.composite_command(None, 30, "", music=music, duration=20))
        self.assertIn('-stream_loop -1 -i "bed.mp3"', text)
        self.assertIn("sidechaincompress", text)
        self.assertEqual(text.count("[a]"), 2)

    def test_moves_may_not_overlap(self):
        with self.assertRaises(C.CardValueError):
            FX.normalise_footage([{"move": "push-in", "at": 2, "out": 6},
                                  {"move": "punch-in", "at": 5, "out": 7}])

    def test_bad_values_are_refused(self):
        for bad in ([{"move": "spin", "at": 1, "out": 3}],
                    [{"move": "pan", "at": 1, "out": 3, "amount": 9}],
                    [{"move": "pan", "at": "1; ls", "out": 3}]):
            with self.assertRaises(C.CardValueError):
                FX.normalise_footage(bad)
        with self.assertRaises(C.CardValueError):
            FX.normalise_grade("sepia")
        with self.assertRaises(C.CardValueError):
            FX.normalise_music({"file": 'a"; ls $HOME #.mp3'})

    def test_moves_past_the_cut_are_dropped_or_clipped(self):
        moves = FX.normalise_footage([{"move": "push-in", "at": 2, "out": 6},
                                      {"move": "pan", "at": 30, "out": 34}], 5)
        self.assertEqual([(m["at"], m["out"]) for m in moves], [(2, 5)])


if __name__ == "__main__":
    unittest.main()
