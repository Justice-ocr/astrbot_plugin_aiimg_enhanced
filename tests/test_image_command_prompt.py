import importlib.util
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "image_command_prompt", Path(__file__).resolve().parents[1] / "core" / "image_command_prompt.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
split_negative_prompt = module.split_negative_prompt


class ImageCommandPromptTests(unittest.TestCase):
    def test_tags_and_weights_are_preserved(self):
        positive = "{artist:ciloranko}, [artist:chen bin], 1girl, solo 2:3"
        self.assertEqual(
            split_negative_prompt(positive + " --negative lowres, bad hands"),
            (positive, "lowres, bad hands"),
        )

    def test_missing_flag_preserves_legacy_prompt(self):
        self.assertEqual(split_negative_prompt("  1girl, solo  "), ("1girl, solo", None))
        self.assertEqual(split_negative_prompt("tag--negative, 1girl"), ("tag--negative, 1girl", None))

    def test_quoted_and_empty_negative(self):
        for quote in ('"', "'"):
            self.assertEqual(split_negative_prompt(f"1girl --negative {quote}{quote}"), ("1girl", ""))
            self.assertEqual(split_negative_prompt(f"1girl --negative {quote}bad hands, text{quote}"), ("1girl", "bad hands, text"))

    def test_readable_labels_and_newlines(self):
        self.assertEqual(
            split_negative_prompt("画师：artist:test\n正面：1girl, solo\n负面：lowres, blurry"),
            ("artist:test, 1girl, solo", "lowres, blurry"),
        )
        self.assertEqual(split_negative_prompt("{artist:test}, 1girl 负面:bad hands"), ("{artist:test}, 1girl", "bad hands"))
        self.assertEqual(split_negative_prompt("正面：1girl 负面："), ("1girl", ""))
        self.assertEqual(split_negative_prompt("画师：artist:test 正面：1girl"), ("artist:test, 1girl", None))

    def test_rejects_duplicate_labels_and_mixed_negative(self):
        for text in ("1girl 负面：lowres --negative blurry", "1girl 负面：bad 正面：solo", "画师： 正面：1girl", "正面：1girl 提示词：solo"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                split_negative_prompt(text)

    def test_invalid_clauses(self):
        for text in ("1girl --negative", "--negative lowres", "1girl --negative text --negative blurry", '1girl --negative "blurry'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                split_negative_prompt(text)
