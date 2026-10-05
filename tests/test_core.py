"""Behaviour tests for crafting.core."""

import unittest

from crafting import core


def make(raw):
    """Parse a raw recipe mapping into a Recipe."""
    return core.parse_recipe(raw)


class ParseRecipeTests(unittest.TestCase):
    def test_zero_amounts_are_rejected(self):
        raw = {"id": "r1", "name": "plate", "inputs": {"ingot": 0},
               "outputs": {"plate": 1}}
        with self.assertRaises(core.CraftingError):
            make(raw)

    def test_malformed_recipes_are_rejected(self):
        good = {"id": "r1", "name": "plate", "inputs": {"ingot": 2},
                "outputs": {"plate": 1}}
        with self.assertRaises(core.CraftingError):
            make(dict(good, outputs={"gear": 1}))
        with self.assertRaises(core.CraftingError):
            make(dict(good, inputs={"ingot": "2"}))
        with self.assertRaises(core.CraftingError):
            make(dict(good, outputs={"plate": -1}))


class RecipeSelectionTests(unittest.TestCase):
    def test_highest_priority_recipe_wins(self):
        low = make({"id": "r_low", "name": "plate", "inputs": {"ingot": 3},
                    "outputs": {"plate": 1}, "priority": 1})
        high = make({"id": "r_high", "name": "plate", "inputs": {"ingot": 2},
                     "outputs": {"plate": 1}, "priority": 7})
        index = core.build_index([low, high])
        self.assertEqual(core.pick_recipe(index, "plate", 0).rid, "r_high")

    def test_workbench_level_gates_recipes(self):
        bench = make({"id": "r_bench", "name": "plate", "inputs": {"ingot": 2},
                      "outputs": {"plate": 1}, "workbench": 1})
        index = core.build_index([bench])
        self.assertEqual(core.pick_recipe(index, "plate", 1).rid, "r_bench")
        self.assertEqual(core.pick_recipe(index, "plate", 4).rid, "r_bench")
        with self.assertRaises(core.CraftingError):
            core.pick_recipe(index, "plate", 0)


class CycleTests(unittest.TestCase):
    def test_every_product_in_a_cycle_is_reported(self):
        recipes = [
            make({"id": "r_a", "name": "plate", "inputs": {"ingot": 1},
                  "outputs": {"plate": 1}}),
            make({"id": "r_b", "name": "ingot", "inputs": {"plate": 1},
                  "outputs": {"ingot": 1}}),
            make({"id": "r_c", "name": "bolt", "inputs": {"bolt": 1},
                  "outputs": {"bolt": 1}}),
            make({"id": "r_d", "name": "rod", "inputs": {"ore": 1},
                  "outputs": {"rod": 1}}),
        ]
        index = core.build_index(recipes)
        self.assertEqual(core.find_cycles(index), ["bolt", "ingot", "plate"])


class CraftTests(unittest.TestCase):
    def test_byproducts_are_added_to_the_inventory(self):
        forge = make({"id": "r_forge", "name": "plate", "inputs": {"ingot": 3},
                      "outputs": {"plate": 2}, "byproducts": {"scale": 1}})
        index = core.build_index([forge])
        stock = {"ingot": 6}
        result = core.craft(stock, index, "plate", 3)
        self.assertEqual(result["plate"], 4)
        self.assertEqual(result["scale"], 2)
        self.assertEqual(result["ingot"], 0)
        self.assertEqual(stock, {"ingot": 6})

    def test_batches_round_up_to_cover_the_requested_count(self):
        forge = make({"id": "r_forge", "name": "plate", "inputs": {"ingot": 3},
                      "outputs": {"plate": 2}})
        index = core.build_index([forge])
        result = core.craft({"ingot": 6}, index, "plate", 3)
        self.assertEqual(result["plate"], 4)
        self.assertEqual(result["ingot"], 0)

    def test_a_missing_tool_stops_the_craft(self):
        drill = make({"id": "r_drill", "name": "hole", "inputs": {"plate": 1},
                      "outputs": {"hole": 1}, "tool": "drill", "tool_uses": 2})
        index = core.build_index([drill])
        self.assertFalse(core.can_craft({"plate": 1}, index, "hole", 1))
        with self.assertRaises(core.CraftingError):
            core.craft({"plate": 1}, index, "hole", 1)
        with self.assertRaises(core.CraftingError):
            core.craft({"plate": 1, "drill": 1}, index, "hole", 1)
        result = core.craft({"plate": 1, "drill": 3}, index, "hole", 1)
        self.assertEqual(result["drill"], 1)
        self.assertEqual(result["hole"], 1)


class StockTests(unittest.TestCase):
    def test_intermediates_are_assembled_before_counting(self):
        recipes = [
            make({"id": "r_gear", "name": "gear", "inputs": {"ingot": 2},
                  "outputs": {"gear": 1}, "workbench": 1}),
            make({"id": "r_turret", "name": "turret", "inputs": {"gear": 3},
                  "outputs": {"turret": 1}, "workbench": 1}),
        ]
        index = core.build_index(recipes)
        self.assertEqual(core.total_stock({"gear": 3}, index, "turret", 2), 1)
        self.assertEqual(core.total_stock({"ingot": 12}, index, "turret", 2), 2)
        self.assertEqual(core.total_stock({"ingot": 4}, index, "turret", 2), 0)


class ConsistencyTests(unittest.TestCase):
    def test_can_craft_agrees_with_the_inventory(self):
        recipes = [
            make({"id": "r_gear", "name": "gear", "inputs": {"ore": 2},
                  "outputs": {"gear": 1}, "workbench": 1}),
            make({"id": "r_shaft", "name": "shaft", "inputs": {"ore": 4},
                  "outputs": {"shaft": 1}, "workbench": 1}),
            make({"id": "r_machine", "name": "machine",
                  "inputs": {"gear": 2, "shaft": 1},
                  "outputs": {"machine": 1}, "workbench": 1}),
        ]
        index = core.build_index(recipes)
        self.assertTrue(core.can_craft({"ore": 8}, index, "machine", 1, 2))
        stocked = {"ore": 6, "gear": 2, "shaft": 1}
        self.assertTrue(core.can_craft(stocked, index, "machine", 1, 2))
        result = core.craft(stocked, index, "machine", 1, 2)
        self.assertEqual(result["machine"], 1)
        self.assertEqual(result["gear"], 0)
        self.assertEqual(result["shaft"], 0)
        self.assertGreaterEqual(min(result.values()), 0)
        self.assertEqual(stocked["gear"], 2)
        scarce = {"ore": 6}
        self.assertFalse(core.can_craft(scarce, index, "machine", 1, 2))
        with self.assertRaises(core.CraftingError):
            core.craft(scarce, index, "machine", 1, 2)


if __name__ == "__main__":
    unittest.main()
