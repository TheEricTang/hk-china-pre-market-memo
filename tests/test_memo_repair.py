import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from memo_repair import REPAIR_SCHEMA, apply_repair, repair_instruction


HEADER = "Morning Market Memo | 17 Sep 2026 | HK/China Pre-Open\n(covers 16 Sep 16:00 HKT close → 17 Sep 06:35 HKT research cutoff)\n\n"
B1 = "- First issuer:  May report a gain. [[Source](https://example.com/1)]  "
B2 = "- Second issuer: Confirmed release. [[Source](https://example.com/2)]"
B3 = "- Third issuer: Confirmed event. [[Source](https://example.com/3)]"
NEW = "- Repaired issuer: Verified report. [[Source](https://example.com/new)]"
MEMO = HEADER + B1 + "\n\n\n" + B2 + "\n\n" + B3 + "\n"


def patch(**updates):
    return {"replacements": [], "additions": [], "order": [], **updates}


class MemoRepairTests(unittest.TestCase):
    def test_noop_is_exact_even_with_nonstandard_whitespace_and_crlf(self):
        for memo in (MEMO, MEMO.rstrip("\n"), MEMO.replace("\n", "\r\n")):
            with self.subTest(memo=repr(memo[-10:])):
                self.assertEqual(apply_repair(memo, patch()), memo)

    def test_single_replacement_preserves_header_and_untouched_bullets_exactly(self):
        result = apply_repair(MEMO, patch(replacements=[{"bullet": 2, "paragraphs": [NEW]}]))
        self.assertEqual(result, HEADER + B1 + "\n\n" + NEW + "\n\n" + B3 + "\n")

    def test_original_indentation_and_trailing_spaces_survive(self):
        memo = MEMO.replace(B1, "  " + B1)
        result = apply_repair(memo, patch(additions=[NEW]))
        self.assertIn("\n  " + B1 + "\n", result)

    def test_splits_and_additions_have_stable_explicit_order_ids(self):
        second = NEW.replace("Repaired", "Another")
        result = apply_repair(MEMO, patch(
            replacements=[{"bullet": 2, "paragraphs": [NEW, second]}], additions=[NEW],
            order=["b2.2", "b1", "a1", "b2.1", "b3"]))
        self.assertEqual(result, HEADER + "\n\n".join([second, B1, NEW, NEW, B3]) + "\n")

    def test_split_without_order_stays_at_original_position(self):
        second = NEW.replace("Repaired", "Another")
        result = apply_repair(MEMO, patch(replacements=[{"bullet": 2, "paragraphs": [NEW, second]}], additions=[NEW]))
        self.assertEqual(result, HEADER + "\n\n".join([B1, NEW, second, B3, NEW]) + "\n")

    def test_explicit_deletion_and_reordering(self):
        result = apply_repair(MEMO, patch(replacements=[{"bullet": 2, "paragraphs": []}], order=["b3", "b1"]))
        self.assertEqual(result, HEADER + B3 + "\n\n" + B1 + "\n")

    def test_invalid_original_replacement_ids_and_duplicates_rejected(self):
        for number in (0, 4, -1, "b1", "1", True, 1.0, None):
            with self.subTest(number=number), self.assertRaisesRegex(ValueError, "unknown"):
                apply_repair(MEMO, patch(replacements=[{"bullet": number, "paragraphs": [NEW]}]))
        with self.assertRaisesRegex(ValueError, "unique"):
            apply_repair(MEMO, patch(replacements=[{"bullet": 1, "paragraphs": [NEW]}, {"bullet": 1, "paragraphs": []}]))

    def test_order_cannot_drop_duplicate_or_invent_ids(self):
        for order in (["b1", "b2"], ["b1", "b2", "b2"], ["b1", "b2", "a1"], ["b1", "b2", "b3", "b4"], [1, "b2", "b3"]):
            with self.subTest(order=order), self.assertRaises(ValueError):
                apply_repair(MEMO, patch(order=order))

    def test_deleted_and_split_parent_ids_cannot_appear_in_order(self):
        for paragraphs, order in (([], ["b1", "b2", "b3"]), ([NEW, NEW], ["b1", "b2", "b3", "b2.1"])):
            with self.subTest(paragraphs=paragraphs), self.assertRaises(ValueError):
                apply_repair(MEMO, patch(replacements=[{"bullet": 2, "paragraphs": paragraphs}], order=order))

    def test_single_replacement_retains_original_id(self):
        result = apply_repair(MEMO, patch(replacements=[{"bullet": 2, "paragraphs": [NEW]}], order=["b2", "b3", "b1"]))
        self.assertEqual(result, HEADER + NEW + "\n\n" + B3 + "\n\n" + B1 + "\n")

    def test_malformed_paragraphs_rejected_for_additions_and_replacements(self):
        bad = ["# New heading", "- No citation", NEW + "\n", NEW + "\r\n", NEW + "\u2028", NEW + "\n- second", NEW.replace("https://", "http://"), "- [bad](https://)", 42]
        for paragraph in bad:
            for edit in (patch(additions=[paragraph]), patch(replacements=[{"bullet": 2, "paragraphs": [paragraph]}])):
                with self.subTest(paragraph=repr(paragraph)), self.assertRaises(ValueError):
                    apply_repair(MEMO, edit)

    def test_invalid_patch_shape_rejected(self):
        invalid = [None, {}, {"replacements": [], "additions": []}, patch(extra=True), patch(order="b1"), patch(replacements=[{"bullet": 1}]), patch(replacements=[{"bullet": 1, "paragraphs": NEW}]), patch(replacements=[{"bullet": 1, "paragraphs": [], "extra": True}])]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                apply_repair(MEMO, item)

    def test_final_paragraph_limit_applies_to_combined_result(self):
        self.assertEqual(apply_repair(MEMO, patch(additions=[NEW] * 37)).count("\n- "), 40)
        with self.assertRaisesRegex(ValueError, "40"):
            apply_repair(MEMO, patch(additions=[NEW] * 38))
        with self.assertRaisesRegex(ValueError, "40"):
            apply_repair(MEMO, patch(replacements=[{"bullet": 1, "paragraphs": [NEW] * 41}]))

    def test_nonbullet_body_cannot_be_silently_lost(self):
        with self.assertRaisesRegex(ValueError, "only single-line"):
            apply_repair(MEMO + "Important trailing prose\n", patch())

    def test_prompt_carries_complete_original_map_and_audit_as_data(self):
        audit = {"items": [{"bullet": 1, "checked_facts": ["verified value"], "source_checks": [{"url": "https://example.com/1"}]}]}
        prompt = repair_instruction(MEMO, audit, ["Fix bullet2 only"])
        payload = json.loads(prompt.split("=== UNTRUSTED REPAIR DATA ===\n", 1)[1].split("\n=== END UNTRUSTED REPAIR DATA ===", 1)[0])
        self.assertEqual(payload["original_bullets"], {"b1": B1, "b2": B2, "b3": B3})
        self.assertEqual(payload["unchangeable_header"], HEADER)
        self.assertEqual(payload["audit"], audit)
        self.assertEqual(payload["errors"], ["Fix bullet2 only"])
        for required in ("Preserve approved facts", "hedges", "fresh independent factual and coverage audit", "untrusted content", "no approval"):
            if required == "no approval":
                self.assertIn("provides no approval", prompt)
            else:
                self.assertIn(required, prompt)

    def test_schema_requires_all_three_fields_and_rejects_extra_keys(self):
        self.assertEqual(set(REPAIR_SCHEMA["required"]), {"replacements", "additions", "order"})
        self.assertFalse(REPAIR_SCHEMA["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
